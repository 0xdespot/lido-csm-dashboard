"""Main service for computing operator rewards."""

from datetime import datetime, timezone
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

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
from ..data.ipfs_logs import BEACON_GENESIS, IPFSLogProvider, epoch_to_datetime as epoch_to_dt
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

        # Step 2: Get bond curve and operator type
        curve_id = await self.onchain.get_bond_curve_id(operator_id)
        operator_type = self.onchain.get_operator_type_name(curve_id)

        # Step 3: Get bond summary
        bond = await self.onchain.get_bond_summary(operator_id)

        # Step 4: Get rewards from merkle tree
        rewards_info = await self.rewards_tree.get_operator_rewards(operator_id)

        # Step 5: Get already distributed (claimed) shares
        distributed = await self.onchain.get_distributed_shares(operator_id)

        # Step 6: Calculate unclaimed
        cumulative_shares = (
            rewards_info.cumulative_fee_shares if rewards_info else 0
        )
        unclaimed_shares = max(0, cumulative_shares - distributed)

        # Step 7: Convert shares to ETH
        unclaimed_eth = await self.onchain.shares_to_eth(unclaimed_shares)
        cumulative_eth = await self.onchain.shares_to_eth(cumulative_shares)
        distributed_eth = await self.onchain.shares_to_eth(distributed)

        # Step 8: Calculate total claimable
        total_claimable = bond.excess_bond_eth + unclaimed_eth

        # Step 9: Get validator details if requested
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

            # Step 10: Calculate APY metrics (using historical IPFS data)
            apy_metrics = await self.calculate_apy_metrics(
                operator_id=operator_id,
                bond_eth=bond.current_bond_eth,
                curve_id=curve_id,
                include_history=include_history,
            )

            # Step 11: Calculate health status
            health_status = await self.calculate_health_status(
                operator_id=operator_id,
                bond=bond,
                stuck_validators_count=operator.stuck_validators_count,
                validator_details=validator_details,
                curve_id=curve_id,
            )

        # Step 12: Fetch withdrawal history if requested
        if include_withdrawals:
            withdrawals = await self.get_withdrawal_history(operator_id)

        return OperatorRewards(
            node_operator_id=operator_id,
            manager_address=operator.manager_address,
            reward_address=operator.reward_address,
            curve_id=curve_id,
            operator_type=operator_type,
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
        curve_id: int = 0,
        include_history: bool = False,
    ) -> APYMetrics:
        """Calculate APY metrics for an operator using historical IPFS data.

        Note: Validator APY (consensus rewards) is NOT calculated because CSM operators
        don't receive those rewards directly - they go to Lido protocol and are
        redistributed via CSM reward distributions (captured in reward_apy).

        Args:
            operator_id: The operator ID
            bond_eth: Current bond in ETH
            curve_id: Bond curve (0=Permissionless, 1=ICS/Legacy EA)
            include_history: If True, populate the frames list with all historical data
                            and calculate accurate per-frame lifetime APY
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
        # Accurate lifetime APY (calculated with per-frame bond when include_history=True)
        lifetime_reward_apy = None
        lifetime_bond_apy = None
        lifetime_net_apy = None
        frame_list: list[DistributionFrame] | None = None
        frames = []

        # 1. Try to get historical APY from IPFS distribution logs
        # Minimum bond threshold: 0.01 ETH (dust amounts produce nonsensical APY)
        MIN_BOND_ETH = Decimal("0.01")
        if bond_eth >= MIN_BOND_ETH:
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
                        if current_days > 0 and bond_eth >= MIN_BOND_ETH:
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
                            if prev_days > 0 and bond_eth >= MIN_BOND_ETH:
                                previous_distribution_apy = round(
                                    float(prev_eth / bond_eth) * (365.0 / prev_days) * 100, 2
                                )

                        # Calculate APY using ETH values (now that we have them)
                        # Calculate 28-day APY (current frame)
                        if current_distribution_apy is not None:
                            historical_reward_apy_28d = current_distribution_apy
                        # NOTE: Lifetime APY is intentionally NOT calculated because:
                        # - It uses current bond as denominator for all historical rewards
                        # - This produces misleading values for operators who grew over time
                        # - We keep lifetime_distribution_eth (ETH totals are accurate)
                        # historical_reward_apy_ltd remains None

                        # Estimate next distribution date (~28 days after current frame ends)
                        # Frame duration ≈ 28 days = ~6300 epochs
                        # If IPFS logs are behind, keep advancing until we get a future date
                        now = datetime.now(timezone.utc)
                        next_epoch = current_frame.end_epoch + 6300
                        next_dt = epoch_to_dt(next_epoch)
                        while next_dt < now:
                            next_epoch += 6300  # Add another ~28 days
                            next_dt = epoch_to_dt(next_epoch)
                        next_distribution_date = next_dt.isoformat()

                        # Estimate next distribution ETH based on current daily rate
                        if current_days > 0:
                            daily_rate = current_eth / Decimal(current_days)
                            next_distribution_est_eth = float(daily_rate * Decimal(28))

            except Exception as e:
                # If historical APY calculation fails, continue without it
                logger.warning(f"Historical APY calculation failed for operator {operator_id}: {e}")

        # 2. Bond APY (stETH protocol rebase rate)
        steth_data = await self.lido_api.get_steth_apr()
        bond_apy = steth_data.get("apr")

        # 3. Net APY calculations (initialized here, calculated after historical APR section)
        net_apy_28d = None
        net_apy_ltd = None

        # Lifetime net APY - intentionally NOT calculated
        # (same reason as historical_reward_apy_ltd - can't accurately calculate without historical bond)
        # net_apy_ltd remains None

        # Current frame net APY and Previous frame net APY are calculated in section 4b/4c
        # after we have historical APR values (current_bond_apr, previous_bond_apy)

        # 4. Calculate bond stETH earnings (from stETH rebasing)
        # Formula: bond_eth * (apr / 100) * (duration_days / 365)
        # Uses historical APR from Lido subgraph when available
        # When include_history=True and we have per-frame validator counts, use accurate bond
        previous_bond_eth = None
        current_bond_eth = None
        lifetime_bond_eth = None
        previous_net_total_eth = None
        current_net_total_eth = None
        lifetime_net_total_eth = None
        previous_bond_apr = None  # Track which APR was used
        current_bond_apr = None
        previous_bond_apy = None  # Bond APY for previous frame (for accurate previous_net_apy)

        # Fetch historical APR data (returns [] if no API key)
        historical_apr_data = await self.lido_api.get_historical_apr_data()

        if bond_eth >= MIN_BOND_ETH:
            # Previous frame bond earnings
            if frames and len(frames) >= 2:
                prev_frame = frames[-2]
                prev_days = self.ipfs_logs.calculate_frame_duration_days(prev_frame)
                if prev_days > 0:
                    # Use average historical APR for the frame period
                    prev_start_ts = BEACON_GENESIS + (prev_frame.start_epoch * 384)
                    prev_end_ts = BEACON_GENESIS + (prev_frame.end_epoch * 384)
                    prev_apr = self.lido_api.get_average_apr_for_range(
                        historical_apr_data, prev_start_ts, prev_end_ts
                    )
                    if prev_apr is None:
                        prev_apr = bond_apy
                    if prev_apr is not None:
                        previous_bond_apr = round(prev_apr, 2)
                        previous_bond_apy = previous_bond_apr  # Same value, used for net APY

                        # When include_history=True and we have validator count, use per-frame bond
                        if include_history and prev_frame.validator_count > 0:
                            prev_bond = self.onchain.calculate_required_bond(
                                prev_frame.validator_count, curve_id
                            )
                            # Keep calculation in Decimal for precision
                            previous_bond_eth = round(
                                float(prev_bond * Decimal(prev_apr / 100) * Decimal(prev_days / 365)), 6
                            )
                        else:
                            previous_bond_eth = round(
                                float(bond_eth * Decimal(prev_apr / 100) * Decimal(prev_days / 365)), 6
                            )

            # Current frame bond earnings
            if frames:
                curr_frame = frames[-1]
                curr_days = self.ipfs_logs.calculate_frame_duration_days(curr_frame)
                if curr_days > 0:
                    # Use average historical APR for the frame period
                    curr_start_ts = BEACON_GENESIS + (curr_frame.start_epoch * 384)
                    curr_end_ts = BEACON_GENESIS + (curr_frame.end_epoch * 384)
                    curr_apr = self.lido_api.get_average_apr_for_range(
                        historical_apr_data, curr_start_ts, curr_end_ts
                    )
                    if curr_apr is None:
                        curr_apr = bond_apy
                    if curr_apr is not None:
                        current_bond_apr = round(curr_apr, 2)
                        # Keep calculation in Decimal for precision
                        current_bond_eth = round(
                            float(bond_eth * Decimal(curr_apr / 100) * Decimal(curr_days / 365)), 6
                        )

            # Lifetime bond earnings (sum of all frame durations with per-frame APR)
            # When include_history=True, calculate accurate lifetime APY with per-frame bond
            # Also build frame_list here to avoid duplicate loop
            if frames:
                lifetime_bond_sum = 0.0
                # For accurate lifetime APY calculation (duration-weighted)
                frame_reward_apys = []
                frame_bond_apys = []
                frame_durations = []
                frame_list = []  # Build frame_list here instead of separate loop

                for i, f in enumerate(frames):
                    f_days = self.ipfs_logs.calculate_frame_duration_days(f)
                    f_eth = await self.onchain.shares_to_eth(f.distributed_rewards)
                    f_apy = None
                    f_bond_apy = None
                    f_net_apy = None

                    if f_days > 0:
                        # Use average historical APR for each frame period
                        f_start_ts = BEACON_GENESIS + (f.start_epoch * 384)
                        f_end_ts = BEACON_GENESIS + (f.end_epoch * 384)
                        f_apr = self.lido_api.get_average_apr_for_range(
                            historical_apr_data, f_start_ts, f_end_ts
                        )
                        if f_apr is None:
                            f_apr = bond_apy

                        if f_apr is not None:
                            # When include_history=True and we have validator count, use per-frame bond
                            if include_history and f.validator_count > 0:
                                f_bond = self.onchain.calculate_required_bond(
                                    f.validator_count, curve_id
                                )
                                # Keep calculations in Decimal for precision
                                lifetime_bond_sum += float(f_bond * Decimal(f_apr / 100) * Decimal(f_days / 365))

                                # Calculate per-frame reward APY using accurate per-frame bond
                                if f_bond > 0:
                                    f_apy = round(float((f_eth / f_bond) * Decimal(365.0 / f_days) * Decimal(100)), 2)
                                    f_bond_apy = round(f_apr, 2)
                                    f_net_apy = round(f_apy + f_bond_apy, 2)

                                    frame_reward_apys.append(f_apy)
                                    frame_bond_apys.append(f_apr)
                                    frame_durations.append(f_days)
                            else:
                                lifetime_bond_sum += float(bond_eth * Decimal(f_apr / 100) * Decimal(f_days / 365))
                                # Fallback: use current bond for APY calc
                                if bond_eth >= MIN_BOND_ETH:
                                    f_apy = round(float(f_eth / bond_eth) * (365.0 / f_days) * 100, 2)

                    # Build frame_list entry if history requested
                    if include_history:
                        frame_list.append(
                            DistributionFrame(
                                frame_number=i + 1,
                                start_date=epoch_to_dt(f.start_epoch).isoformat(),
                                end_date=epoch_to_dt(f.end_epoch).isoformat(),
                                rewards_eth=float(f_eth),
                                rewards_shares=f.distributed_rewards,
                                duration_days=round(f_days, 1),
                                validator_count=f.validator_count,
                                apy=f_apy,
                                bond_apy=f_bond_apy,
                                net_apy=f_net_apy,
                            )
                        )

                if lifetime_bond_sum > 0:
                    lifetime_bond_eth = round(lifetime_bond_sum, 6)

                # Calculate duration-weighted lifetime APYs when include_history=True
                if include_history and frame_durations:
                    total_duration = sum(frame_durations)
                    if total_duration > 0:
                        # Duration-weighted average reward APY
                        lifetime_reward_apy = round(
                            sum(apy * dur for apy, dur in zip(frame_reward_apys, frame_durations))
                            / total_duration,
                            2
                        )
                        # Duration-weighted average bond APY
                        lifetime_bond_apy = round(
                            sum(apy * dur for apy, dur in zip(frame_bond_apys, frame_durations))
                            / total_duration,
                            2
                        )
                        # Net = Reward + Bond
                        lifetime_net_apy = round(lifetime_reward_apy + lifetime_bond_apy, 2)

        # 4b. Previous frame net APY (now that we have previous_bond_apy)
        # Uses the actual APR from the previous frame period instead of current bond_apy
        if previous_distribution_apy is not None:
            prev_bond_apy_to_use = previous_bond_apy if previous_bond_apy is not None else bond_apy
            if prev_bond_apy_to_use is not None:
                previous_net_apy = round(previous_distribution_apy + prev_bond_apy_to_use, 2)

        # 4c. Current frame net APY (using historical APR when available, like previous frame)
        if historical_reward_apy_28d is not None:
            curr_bond_apy_to_use = current_bond_apr if current_bond_apr is not None else bond_apy
            if curr_bond_apy_to_use is not None:
                net_apy_28d = round(historical_reward_apy_28d + curr_bond_apy_to_use, 2)
        elif bond_apy is not None:
            net_apy_28d = round(bond_apy, 2)

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

        return APYMetrics(
            previous_distribution_eth=previous_distribution_eth,
            previous_distribution_apy=previous_distribution_apy,
            previous_net_apy=previous_net_apy,
            current_distribution_eth=current_distribution_eth,
            current_distribution_apy=current_distribution_apy,
            next_distribution_date=next_distribution_date,
            next_distribution_est_eth=next_distribution_est_eth,
            lifetime_distribution_eth=lifetime_distribution_eth,
            lifetime_reward_apy=lifetime_reward_apy,
            lifetime_bond_apy=lifetime_bond_apy,
            lifetime_net_apy=lifetime_net_apy,
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
        curve_id: int | None = None,
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

        # Get strikes data (pass curve_id for operator-specific thresholds)
        strike_summary = StrikeSummary()
        try:
            summary = await self.strikes.get_operator_strike_summary(operator_id, curve_id)
            strike_summary = StrikeSummary(
                total_validators_with_strikes=summary.get("total_validators_with_strikes", 0),
                validators_at_risk=summary.get("validators_at_risk", 0),
                validators_near_ejection=summary.get("validators_near_ejection", 0),
                total_strikes=summary.get("total_strikes", 0),
                max_strikes=summary.get("max_strikes", 0),
                strike_threshold=summary.get("strike_threshold", 3),
            )
        except Exception as e:
            # If strikes fetch fails, continue with empty summary
            logger.warning(f"Failed to fetch strikes for operator {operator_id}: {e}")

        return HealthStatus(
            bond_healthy=bond_healthy,
            bond_deficit_eth=bond_deficit,
            stuck_validators_count=stuck_validators_count,
            slashed_validators_count=slashed_count,
            validators_at_risk_count=at_risk_count,
            strikes=strike_summary,
        )

    async def get_operator_strikes(self, operator_id: int, curve_id: int | None = None):
        """Get detailed strikes for an operator's validators.

        Args:
            operator_id: The CSM operator ID
            curve_id: The operator's bond curve ID (determines strike threshold)
        """
        return await self.strikes.get_operator_strikes(operator_id, curve_id)

    async def get_recent_frame_dates(self, count: int = 6) -> list[dict]:
        """Get date ranges for the most recent N distribution frames.

        Returns list of {start, end} dicts with formatted date strings,
        ordered from oldest to newest (matching strikes array order).
        """
        try:
            log_history = await self.onchain.get_distribution_log_history()
        except Exception as e:
            logger.warning(f"Failed to fetch distribution log history: {e}")
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
            except Exception as e:
                # Skip frames we can't fetch
                logger.debug(f"Failed to fetch frame data for CID {entry.get('logCid', 'unknown')}: {e}")
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
        except Exception as e:
            logger.debug(f"Failed to get active_since for operator {operator_id}: {e}")
            return None

    async def get_withdrawal_history(self, operator_id: int) -> list[WithdrawalEvent]:
        """Get withdrawal/claim history for an operator.

        Returns list of WithdrawalEvent objects representing when rewards were claimed.
        Includes both stETH direct transfers and unstETH (withdrawal NFT) claims.
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
                    withdrawal_type=e.get("withdrawal_type", "stETH"),
                    request_id=e.get("request_id"),
                    status=e.get("status"),
                    claimed_eth=e.get("claimed_eth"),
                    claim_tx_hash=e.get("claim_tx_hash"),
                    claim_timestamp=e.get("claim_timestamp"),
                )
                for e in events
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch withdrawal history for operator {operator_id}: {e}")
            return []
