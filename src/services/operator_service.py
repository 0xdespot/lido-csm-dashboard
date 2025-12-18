"""Main service for computing operator rewards."""

from decimal import Decimal

from ..core.types import APYMetrics, BondSummary, HealthStatus, OperatorRewards, StrikeSummary
from ..data.beacon import (
    BeaconDataProvider,
    ValidatorInfo,
    aggregate_validator_status,
    calculate_avg_effectiveness,
    count_at_risk_validators,
    count_slashed_validators,
    get_earliest_activation,
)
from ..data.ipfs_logs import IPFSLogProvider
from ..data.lido_api import LidoAPIProvider
from ..data.onchain import OnChainDataProvider
from ..data.rewards_tree import RewardsTreeProvider
from ..data.strikes import StrikesProvider


class OperatorService:
    """Orchestrates data from multiple sources to compute final rewards."""

    def __init__(self, rpc_url: str | None = None):
        self.onchain = OnChainDataProvider(rpc_url)
        self.rewards_tree = RewardsTreeProvider()
        self.beacon = BeaconDataProvider()
        self.lido_api = LidoAPIProvider()
        self.ipfs_logs = IPFSLogProvider()
        self.strikes = StrikesProvider(rpc_url)

    async def get_operator_by_address(
        self, address: str, include_validators: bool = False
    ) -> OperatorRewards | None:
        """
        Main entry point: get complete rewards data for an address.
        Returns None if address is not a CSM operator.
        """
        # Step 1: Find operator ID by address
        operator_id = await self.onchain.find_operator_by_address(address)
        if operator_id is None:
            return None

        return await self.get_operator_by_id(operator_id, include_validators)

    async def get_operator_by_id(
        self, operator_id: int, include_validators: bool = False
    ) -> OperatorRewards | None:
        """Get complete rewards data for an operator ID."""
        from web3.exceptions import ContractLogicError

        # Step 1: Get operator info
        try:
            operator = await self.onchain.get_node_operator(operator_id)
        except ContractLogicError:
            # Operator ID doesn't exist on-chain
            return None

        # Step 2: Get bond summary
        bond = await self.onchain.get_bond_summary(operator_id)

        # Step 3: Get rewards from merkle tree
        rewards_info = await self.rewards_tree.get_operator_rewards(operator_id)

        # Step 4: Get already distributed (claimed) shares
        distributed = await self.onchain.get_distributed_shares(operator_id)

        # Step 5: Calculate unclaimed
        cumulative_shares = (
            rewards_info.cumulative_fee_shares if rewards_info else 0
        )
        unclaimed_shares = max(0, cumulative_shares - distributed)

        # Step 6: Convert shares to ETH
        unclaimed_eth = await self.onchain.shares_to_eth(unclaimed_shares)
        cumulative_eth = await self.onchain.shares_to_eth(cumulative_shares)
        distributed_eth = await self.onchain.shares_to_eth(distributed)

        # Step 7: Calculate total claimable
        total_claimable = bond.excess_bond_eth + unclaimed_eth

        # Step 8: Get validator details if requested
        validator_details: list[ValidatorInfo] = []
        validators_by_status: dict[str, int] | None = None
        avg_effectiveness: float | None = None
        apy_metrics: APYMetrics | None = None
        active_since = None
        health_status: HealthStatus | None = None

        if include_validators and operator.total_deposited_keys > 0:
            # Get validator pubkeys
            pubkeys = await self.onchain.get_signing_keys(
                operator_id, 0, operator.total_deposited_keys
            )
            # Fetch validator status from beacon chain
            validator_details = await self.beacon.get_validators_by_pubkeys(pubkeys)
            validators_by_status = aggregate_validator_status(validator_details)
            avg_effectiveness = calculate_avg_effectiveness(validator_details)
            active_since = get_earliest_activation(validator_details)

            # Step 9: Calculate APY metrics (using historical IPFS data)
            apy_metrics = await self.calculate_apy_metrics(
                operator_id=operator_id,
                bond_eth=bond.current_bond_eth,
            )

            # Step 10: Calculate health status
            health_status = await self.calculate_health_status(
                operator_id=operator_id,
                bond=bond,
                stuck_validators_count=operator.stuck_validators_count,
                validator_details=validator_details,
            )

        return OperatorRewards(
            node_operator_id=operator_id,
            manager_address=operator.manager_address,
            reward_address=operator.reward_address,
            current_bond_eth=bond.current_bond_eth,
            required_bond_eth=bond.required_bond_eth,
            excess_bond_eth=bond.excess_bond_eth,
            cumulative_rewards_shares=cumulative_shares,
            cumulative_rewards_eth=cumulative_eth,
            distributed_shares=distributed,
            distributed_eth=distributed_eth,
            unclaimed_shares=unclaimed_shares,
            unclaimed_eth=unclaimed_eth,
            total_claimable_eth=total_claimable,
            total_validators=operator.total_deposited_keys,
            active_validators=operator.total_deposited_keys - operator.total_exited_keys,
            exited_validators=operator.total_exited_keys,
            validator_details=validator_details,
            validators_by_status=validators_by_status,
            avg_effectiveness=avg_effectiveness,
            apy=apy_metrics,
            active_since=active_since,
            health=health_status,
        )

    async def get_all_operators_with_rewards(self) -> list[int]:
        """Get list of all operator IDs that have rewards in the tree."""
        return await self.rewards_tree.get_all_operators_with_rewards()

    async def calculate_apy_metrics(
        self,
        operator_id: int,
        bond_eth: Decimal,
    ) -> APYMetrics:
        """Calculate APY metrics for an operator using historical IPFS data.

        Note: Validator APY (consensus rewards) is NOT calculated because CSM operators
        don't receive those rewards directly - they go to Lido protocol and are
        redistributed via CSM reward distributions (captured in reward_apy).
        """
        historical_reward_apy_28d = None
        historical_reward_apy_ltd = None

        # 1. Try to get historical APY from IPFS distribution logs
        if bond_eth > 0:
            try:
                # Query historical log CIDs from contract events
                log_history = await self.onchain.get_distribution_log_history()

                if log_history:
                    # Fetch operator's historical frame data
                    frames = await self.ipfs_logs.get_operator_history(
                        operator_id, log_history
                    )

                    if frames:
                        # Calculate APY for 28-day and lifetime periods
                        apy_results = self.ipfs_logs.calculate_historical_apy(
                            frames=frames,
                            bond_eth=bond_eth,
                            periods=[28, None],  # 28-day and lifetime
                        )
                        historical_reward_apy_28d = apy_results.get("28d")
                        historical_reward_apy_ltd = apy_results.get("ltd")
            except Exception:
                # If historical APY calculation fails, continue without it
                pass

        # 2. Bond APY (stETH protocol rebase rate)
        steth_data = await self.lido_api.get_steth_apr()
        bond_apy = steth_data.get("apr")

        # 3. Net APY (Historical Reward APY + Bond APY)
        net_apy_28d = None
        net_apy_ltd = None

        if historical_reward_apy_28d is not None and bond_apy is not None:
            net_apy_28d = historical_reward_apy_28d + bond_apy
        elif bond_apy is not None:
            net_apy_28d = bond_apy

        if historical_reward_apy_ltd is not None and bond_apy is not None:
            net_apy_ltd = historical_reward_apy_ltd + bond_apy
        elif bond_apy is not None:
            net_apy_ltd = bond_apy

        return APYMetrics(
            historical_reward_apy_28d=historical_reward_apy_28d,
            historical_reward_apy_ltd=historical_reward_apy_ltd,
            bond_apy=bond_apy,
            net_apy_28d=net_apy_28d,
            net_apy_ltd=net_apy_ltd,
        )

    async def calculate_health_status(
        self,
        operator_id: int,
        bond: BondSummary,
        stuck_validators_count: int,
        validator_details: list[ValidatorInfo],
    ) -> HealthStatus:
        """Calculate health status for an operator.

        Includes bond health, stuck validators, slashing, at-risk validators, and strikes.
        """
        # Bond health
        bond_healthy = bond.current_bond_eth >= bond.required_bond_eth
        bond_deficit = max(Decimal(0), bond.required_bond_eth - bond.current_bond_eth)

        # Count slashed and at-risk validators
        slashed_count = count_slashed_validators(validator_details)
        at_risk_count = count_at_risk_validators(validator_details)

        # Get strikes data
        strike_summary = StrikeSummary()
        try:
            summary = await self.strikes.get_operator_strike_summary(operator_id)
            strike_summary = StrikeSummary(
                total_validators_with_strikes=summary["total_validators_with_strikes"],
                validators_at_risk=summary["validators_at_risk"],
                validators_near_ejection=summary["validators_near_ejection"],
                total_strikes=summary["total_strikes"],
                max_strikes=summary["max_strikes"],
            )
        except Exception:
            # If strikes fetch fails, continue with empty summary
            pass

        return HealthStatus(
            bond_healthy=bond_healthy,
            bond_deficit_eth=bond_deficit,
            stuck_validators_count=stuck_validators_count,
            slashed_validators_count=slashed_count,
            validators_at_risk_count=at_risk_count,
            strikes=strike_summary,
        )

    async def get_operator_strikes(self, operator_id: int):
        """Get detailed strikes for an operator's validators."""
        return await self.strikes.get_operator_strikes(operator_id)
