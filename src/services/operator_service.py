"""Main service for computing operator rewards."""

from decimal import Decimal

from ..core.types import APYMetrics, OperatorRewards
from ..data.beacon import (
    BeaconDataProvider,
    ValidatorInfo,
    aggregate_validator_status,
    calculate_avg_effectiveness,
)
from ..data.lido_api import LidoAPIProvider
from ..data.onchain import OnChainDataProvider
from ..data.rewards_tree import RewardsTreeProvider


class OperatorService:
    """Orchestrates data from multiple sources to compute final rewards."""

    def __init__(self, rpc_url: str | None = None):
        self.onchain = OnChainDataProvider(rpc_url)
        self.rewards_tree = RewardsTreeProvider()
        self.beacon = BeaconDataProvider()
        self.lido_api = LidoAPIProvider()

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

        # Step 7: Calculate total claimable
        total_claimable = bond.excess_bond_eth + unclaimed_eth

        # Step 8: Get validator details if requested
        validator_details: list[ValidatorInfo] = []
        validators_by_status: dict[str, int] | None = None
        avg_effectiveness: float | None = None
        apy_metrics: APYMetrics | None = None

        if include_validators and operator.total_deposited_keys > 0:
            # Get validator pubkeys
            pubkeys = await self.onchain.get_signing_keys(
                operator_id, 0, operator.total_deposited_keys
            )
            # Fetch validator status from beacon chain
            validator_details = await self.beacon.get_validators_by_pubkeys(pubkeys)
            validators_by_status = aggregate_validator_status(validator_details)
            avg_effectiveness = calculate_avg_effectiveness(validator_details)

            # Step 9: Calculate APY metrics
            apy_metrics = await self.calculate_apy_metrics(
                bond_eth=bond.current_bond_eth,
                unclaimed_eth=unclaimed_eth,
            )

        return OperatorRewards(
            node_operator_id=operator_id,
            manager_address=operator.manager_address,
            reward_address=operator.reward_address,
            current_bond_eth=bond.current_bond_eth,
            required_bond_eth=bond.required_bond_eth,
            excess_bond_eth=bond.excess_bond_eth,
            cumulative_rewards_shares=cumulative_shares,
            distributed_shares=distributed,
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
        )

    async def get_all_operators_with_rewards(self) -> list[int]:
        """Get list of all operator IDs that have rewards in the tree."""
        return await self.rewards_tree.get_all_operators_with_rewards()

    async def calculate_apy_metrics(
        self,
        bond_eth: Decimal,
        unclaimed_eth: Decimal,
    ) -> APYMetrics:
        """Calculate APY metrics for an operator.

        Note: Validator APY (consensus rewards) is NOT calculated because CSM operators
        don't receive those rewards directly - they go to Lido protocol and are
        redistributed via CSM reward distributions (captured in reward_apy).
        """
        # 1. Reward APY (CSM reward distributions)
        # Estimate based on unclaimed rewards / bond over 28-day frame
        reward_apy_7d = None
        reward_apy_28d = None

        if bond_eth > 0 and unclaimed_eth > 0:
            # CSM rewards accrue in 28-day frames
            reward_apy_28d = float(
                unclaimed_eth / bond_eth * Decimal(365.25 / 28) * 100
            )
            # Use same estimate for 7-day (without historical data)
            reward_apy_7d = reward_apy_28d

        # 2. Bond APY (stETH protocol rebase rate)
        steth_data = await self.lido_api.get_steth_apr()
        bond_apy = steth_data.get("apr")

        # 3. Net APY (Reward APY + Bond APY)
        net_apy_7d = None
        net_apy_28d = None

        if reward_apy_7d is not None and bond_apy is not None:
            net_apy_7d = reward_apy_7d + bond_apy
        elif bond_apy is not None:
            net_apy_7d = bond_apy

        if reward_apy_28d is not None and bond_apy is not None:
            net_apy_28d = reward_apy_28d + bond_apy
        elif bond_apy is not None:
            net_apy_28d = bond_apy

        return APYMetrics(
            reward_apy_7d=reward_apy_7d,
            reward_apy_28d=reward_apy_28d,
            bond_apy=bond_apy,
            net_apy_7d=net_apy_7d,
            net_apy_28d=net_apy_28d,
        )
