"""Main service for computing operator rewards."""

from decimal import Decimal

from ..core.types import (
    APYMetrics,
    BondSummary,
    DistributionFrame,
    HealthStatus,
    OperatorRewards,
    StrikeSummary,
    WithdrawalEvent,
)
from ..data.beacon import (
    BeaconDataProvider,
    ValidatorInfo,
    aggregate_validator_status,
    calculate_avg_effectiveness,
    count_at_risk_validators,
    count_slashed_validators,
    epoch_to_datetime,
    get_earliest_activation,
)
from ..data.ipfs_logs import IPFSLogProvider, epoch_to_datetime as epoch_to_dt
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
        self, address: str, include_validators: bool = False, include_history: bool = False, include_withdrawals: bool = False
    ) -> OperatorRewards | None:
        """
        Main entry point: get complete rewards data for an address.
        Returns None if address is not a CSM operator.
        """
        # Step 1: Find operator ID by address
        operator_id = await self.onchain.find_operator_by_address(address)
        if operator_id is None:
            return None

        return await self.get_operator_by_id(operator_id, include_validators, include_history, include_withdrawals)

    async def get_operator_by_id(
        self, operator_id: int, include_validators: bool = False, include_history: bool = False, include_withdrawals: bool = False
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
        withdrawals: list[WithdrawalEvent] | None = None

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
                include_history=include_history,
            )

            # Step 10: Calculate health status
            health_status = await self.calculate_health_status(
                operator_id=operator_id,
                bond=bond,
                stuck_validators_count=operator.stuck_validators_count,
                validator_details=validator_details,
            )

        # Step 11: Fetch withdrawal history if requested
        if include_withdrawals:
            withdrawals = await self.get_withdrawal_history(operator_id)

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
            withdrawals=withdrawals,
        )

    async def get_all_operators_with_rewards(self) -> list[int]:
        """Get list of all operator IDs that have rewards in the tree."""
        return await self.rewards_tree.get_all_operators_with_rewards()

    async def calculate_apy_metrics(
        self,
        operator_id: int,
        bond_eth: Decimal,
        include_history: bool = False,
    ) -> APYMetrics:
        """Calculate APY metrics for an operator using historical IPFS data.

        Note: Validator APY (consensus rewards) is NOT calculated because CSM operators
        don't receive those rewards directly - they go to Lido protocol and are
        redistributed via CSM reward distributions (captured in reward_apy).

        Args:
            operator_id: The operator ID
            bond_eth: Current bond in ETH
            include_history: If True, populate the frames list with all historical data
        """
        historical_reward_apy_28d = None
        historical_reward_apy_ltd = None
        previous_distribution_eth = None
        previous_distribution_apy = None
        previous_net_apy = None
        current_distribution_eth = None
        current_distribution_apy = None
        next_distribution_date = None
        next_distribution_est_eth = None
        lifetime_distribution_eth = None
        frame_list: list[DistributionFrame] | None = None
        frames = []

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
                        # Convert all frame shares to ETH values
                        # IPFS logs store distributed_rewards in stETH shares, not ETH
                        # We need to convert shares to ETH for accurate display and APY calculation
                        total_shares = sum(f.distributed_rewards for f in frames)
                        lifetime_distribution_eth = float(
                            await self.onchain.shares_to_eth(total_shares)
                        )

                        # Extract current frame data (most recent)
                        current_frame = frames[-1]
                        current_eth = await self.onchain.shares_to_eth(
                            current_frame.distributed_rewards
                        )
                        current_days = self.ipfs_logs.calculate_frame_duration_days(current_frame)
                        current_distribution_eth = float(current_eth)
                        if current_days > 0:
                            current_distribution_apy = round(
                                float(current_eth / bond_eth) * (365.0 / current_days) * 100, 2
                            )

                        # Extract previous frame data (second-to-last)
                        if len(frames) >= 2:
                            previous_frame = frames[-2]
                            prev_eth = await self.onchain.shares_to_eth(
                                previous_frame.distributed_rewards
                            )
                            prev_days = self.ipfs_logs.calculate_frame_duration_days(previous_frame)
                            previous_distribution_eth = float(prev_eth)
                            if prev_days > 0:
                                previous_distribution_apy = round(
                                    float(prev_eth / bond_eth) * (365.0 / prev_days) * 100, 2
                                )

                        # Calculate APY using ETH values (now that we have them)
                        # Calculate 28-day APY (current frame)
                        if current_distribution_apy is not None:
                            historical_reward_apy_28d = current_distribution_apy
                        # Calculate lifetime APY
                        if lifetime_distribution_eth > 0:
                            total_days = sum(
                                self.ipfs_logs.calculate_frame_duration_days(f) for f in frames
                            )
                            if total_days > 0:
                                historical_reward_apy_ltd = round(
                                    (lifetime_distribution_eth / float(bond_eth))
                                    * (365.0 / total_days)
                                    * 100,
                                    2,
                                )

                        # Estimate next distribution date (~28 days after current frame ends)
                        # Frame duration ≈ 28 days = ~6300 epochs
                        next_epoch = current_frame.end_epoch + 6300
                        next_distribution_date = epoch_to_dt(next_epoch).isoformat()

                        # Estimate next distribution ETH based on current daily rate
                        if current_days > 0:
                            daily_rate = current_eth / Decimal(current_days)
                            next_distribution_est_eth = float(daily_rate * Decimal(28))

            except Exception:
                # If historical APY calculation fails, continue without it
                pass

        # 2. Bond APY (stETH protocol rebase rate)
        steth_data = await self.lido_api.get_steth_apr()
        bond_apy = steth_data.get("apr")

        # 3. Net APY calculations
        net_apy_28d = None
        net_apy_ltd = None

        # Current frame net APY (historical_reward_apy_28d is basically current frame APY)
        if historical_reward_apy_28d is not None and bond_apy is not None:
            net_apy_28d = round(historical_reward_apy_28d + bond_apy, 2)
        elif bond_apy is not None:
            net_apy_28d = round(bond_apy, 2)

        # Lifetime net APY
        if historical_reward_apy_ltd is not None and bond_apy is not None:
            net_apy_ltd = round(historical_reward_apy_ltd + bond_apy, 2)
        elif bond_apy is not None:
            net_apy_ltd = round(bond_apy, 2)

        # Previous frame net APY (uses current bond_apy as approximation)
        if previous_distribution_apy is not None and bond_apy is not None:
            previous_net_apy = round(previous_distribution_apy + bond_apy, 2)

        # 4. Calculate bond stETH earnings (from stETH rebasing)
        # Formula: bond_eth * (apr / 100) * (duration_days / 365)
        # Uses historical APR from Lido subgraph when available
        previous_bond_eth = None
        current_bond_eth = None
        lifetime_bond_eth = None
        previous_net_total_eth = None
        current_net_total_eth = None
        lifetime_net_total_eth = None
        previous_bond_apr = None  # Track which APR was used
        current_bond_apr = None

        # Fetch historical APR data (returns [] if no API key)
        historical_apr_data = await self.lido_api.get_historical_apr_data()

        if bond_eth > 0:
            # Previous frame bond earnings
            if frames and len(frames) >= 2:
                prev_frame = frames[-2]
                prev_days = self.ipfs_logs.calculate_frame_duration_days(prev_frame)
                if prev_days > 0:
                    # Use historical APR if available, otherwise fall back to current
                    prev_apr = self.lido_api.get_apr_for_block(
                        historical_apr_data, prev_frame.block_number
                    )
                    if prev_apr is None:
                        prev_apr = bond_apy
                    if prev_apr is not None:
                        previous_bond_apr = round(prev_apr, 2)
                        previous_bond_eth = round(
                            float(bond_eth) * (prev_apr / 100) * (prev_days / 365), 6
                        )

            # Current frame bond earnings
            if frames:
                curr_frame = frames[-1]
                curr_days = self.ipfs_logs.calculate_frame_duration_days(curr_frame)
                if curr_days > 0:
                    # Use historical APR if available, otherwise fall back to current
                    curr_apr = self.lido_api.get_apr_for_block(
                        historical_apr_data, curr_frame.block_number
                    )
                    if curr_apr is None:
                        curr_apr = bond_apy
                    if curr_apr is not None:
                        current_bond_apr = round(curr_apr, 2)
                        current_bond_eth = round(
                            float(bond_eth) * (curr_apr / 100) * (curr_days / 365), 6
                        )

            # Lifetime bond earnings (sum of all frame durations with per-frame APR)
            if frames:
                lifetime_bond_sum = 0.0
                for f in frames:
                    f_days = self.ipfs_logs.calculate_frame_duration_days(f)
                    if f_days > 0:
                        f_apr = self.lido_api.get_apr_for_block(
                            historical_apr_data, f.block_number
                        )
                        if f_apr is None:
                            f_apr = bond_apy
                        if f_apr is not None:
                            lifetime_bond_sum += float(bond_eth) * (f_apr / 100) * (f_days / 365)
                if lifetime_bond_sum > 0:
                    lifetime_bond_eth = round(lifetime_bond_sum, 6)

        # 5. Calculate net totals (Rewards + Bond)
        if previous_distribution_eth is not None or previous_bond_eth is not None:
            previous_net_total_eth = round(
                (previous_distribution_eth or 0) + (previous_bond_eth or 0), 6
            )
        if current_distribution_eth is not None or current_bond_eth is not None:
            current_net_total_eth = round(
                (current_distribution_eth or 0) + (current_bond_eth or 0), 6
            )
        if lifetime_distribution_eth is not None or lifetime_bond_eth is not None:
            lifetime_net_total_eth = round(
                (lifetime_distribution_eth or 0) + (lifetime_bond_eth or 0), 6
            )

        # 6. Build frame history if requested
        if include_history and frames:
            frame_list = []
            for i, f in enumerate(frames):
                # Convert shares to ETH (not just dividing by 10^18)
                f_eth = await self.onchain.shares_to_eth(f.distributed_rewards)
                f_days = self.ipfs_logs.calculate_frame_duration_days(f)
                f_apy = None
                if f_days > 0 and bond_eth > 0:
                    f_apy = round(float(f_eth / bond_eth) * (365.0 / f_days) * 100, 2)

                frame_list.append(
                    DistributionFrame(
                        frame_number=i + 1,
                        start_date=epoch_to_dt(f.start_epoch).isoformat(),
                        end_date=epoch_to_dt(f.end_epoch).isoformat(),
                        rewards_eth=float(f_eth),
                        rewards_shares=f.distributed_rewards,
                        duration_days=round(f_days, 1),
                        apy=f_apy,
                    )
                )

        return APYMetrics(
            previous_distribution_eth=previous_distribution_eth,
            previous_distribution_apy=previous_distribution_apy,
            previous_net_apy=previous_net_apy,
            current_distribution_eth=current_distribution_eth,
            current_distribution_apy=current_distribution_apy,
            next_distribution_date=next_distribution_date,
            next_distribution_est_eth=next_distribution_est_eth,
            lifetime_distribution_eth=lifetime_distribution_eth,
            historical_reward_apy_28d=historical_reward_apy_28d,
            historical_reward_apy_ltd=historical_reward_apy_ltd,
            bond_apy=bond_apy,
            net_apy_28d=net_apy_28d,
            net_apy_ltd=net_apy_ltd,
            frames=frame_list,
            previous_bond_eth=previous_bond_eth,
            current_bond_eth=current_bond_eth,
            lifetime_bond_eth=lifetime_bond_eth,
            previous_bond_apr=previous_bond_apr,
            current_bond_apr=current_bond_apr,
            uses_historical_apr=bool(historical_apr_data),
            previous_net_total_eth=previous_net_total_eth,
            current_net_total_eth=current_net_total_eth,
            lifetime_net_total_eth=lifetime_net_total_eth,
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
                total_validators_with_strikes=summary.get("total_validators_with_strikes", 0),
                validators_at_risk=summary.get("validators_at_risk", 0),
                validators_near_ejection=summary.get("validators_near_ejection", 0),
                total_strikes=summary.get("total_strikes", 0),
                max_strikes=summary.get("max_strikes", 0),
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

    async def get_recent_frame_dates(self, count: int = 6) -> list[dict]:
        """Get date ranges for the most recent N distribution frames.

        Returns list of {start, end} dicts with formatted date strings,
        ordered from oldest to newest (matching strikes array order).
        """
        try:
            log_history = await self.onchain.get_distribution_log_history()
        except Exception:
            return []

        if not log_history:
            return []

        # Get last N frames (log_history is already sorted oldest-first)
        recent_logs = log_history[-count:] if len(log_history) >= count else log_history

        frame_dates = []
        for entry in recent_logs:
            try:
                log_data = await self.ipfs_logs.fetch_log(entry["logCid"])
                if log_data:
                    start_epoch, end_epoch = self.ipfs_logs.get_frame_info(log_data)
                    start_date = epoch_to_datetime(start_epoch)
                    end_date = epoch_to_datetime(end_epoch)
                    frame_dates.append({
                        "start": start_date.strftime("%b %d"),
                        "end": end_date.strftime("%b %d"),
                    })
            except Exception:
                # Skip frames we can't fetch
                continue

        # Pad to ensure we always have `count` entries (for UI consistency)
        # Pad at the beginning since strikes array is ordered oldest to newest
        frame_number = 1
        while len(frame_dates) < count:
            frame_dates.insert(0, {"start": f"Frame {frame_number}", "end": ""})
            frame_number += 1

        return frame_dates

    async def get_operator_active_since(self, operator_id: int):
        """Get operator's first validator activation date (lightweight).

        Returns datetime or None if no validators have been activated.
        """
        from datetime import datetime

        try:
            operator = await self.onchain.get_node_operator(operator_id)
            if operator.total_deposited_keys == 0:
                return None

            # Get just the first pubkey to minimize beacon chain API calls
            pubkeys = await self.onchain.get_signing_keys(operator_id, 0, 1)
            if not pubkeys:
                return None

            validators = await self.beacon.get_validators_by_pubkeys(pubkeys)
            return get_earliest_activation(validators)
        except Exception:
            return None

    async def get_withdrawal_history(self, operator_id: int) -> list[WithdrawalEvent]:
        """Get withdrawal/claim history for an operator.

        Returns list of WithdrawalEvent objects representing when rewards were claimed.
        """
        try:
            operator = await self.onchain.get_node_operator(operator_id)
            events = await self.onchain.get_withdrawal_history(operator.reward_address)
            return [
                WithdrawalEvent(
                    block_number=e["block_number"],
                    timestamp=e["timestamp"],
                    shares=e["shares"],
                    eth_value=e["eth_value"],
                    tx_hash=e["tx_hash"],
                )
                for e in events
            ]
        except Exception:
            return []
