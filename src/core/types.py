"""Data models for CSM Dashboard."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..data.beacon import ValidatorInfo


class NodeOperator(BaseModel):
    """Node operator data from CSModule contract."""

    node_operator_id: int
    total_added_keys: int
    total_withdrawn_keys: int
    total_deposited_keys: int
    total_vetted_keys: int
    stuck_validators_count: int
    depositable_validators_count: int
    target_limit: int
    target_limit_mode: int
    total_exited_keys: int
    enqueued_count: int
    manager_address: str
    proposed_manager_address: str
    reward_address: str
    proposed_reward_address: str
    extended_manager_permissions: bool


class BondSummary(BaseModel):
    """Bond information for an operator."""

    current_bond_wei: int
    required_bond_wei: int
    current_bond_eth: Decimal
    required_bond_eth: Decimal
    excess_bond_eth: Decimal


class RewardsInfo(BaseModel):
    """Rewards data from merkle tree."""

    cumulative_fee_shares: int
    proof: list[str]


class DistributionFrame(BaseModel):
    """Single distribution frame data."""

    frame_number: int
    start_date: str  # ISO format
    end_date: str
    rewards_eth: float
    rewards_shares: int
    duration_days: float
    validator_count: int = 0  # Number of validators in this frame
    apy: float | None = None  # Annualized for this frame (kept for backwards compat)


class WithdrawalEvent(BaseModel):
    """A single reward claim/withdrawal event."""

    block_number: int
    timestamp: str  # ISO format
    shares: int
    eth_value: float
    tx_hash: str


class APYMetrics(BaseModel):
    """APY calculations for an operator.

    Note: Validator APY (consensus rewards) is NOT included because CSM operators
    don't receive those rewards directly - they go to Lido protocol and are
    redistributed via CSM reward distributions (captured in reward_apy).

    Historical APY is calculated from actual distributed rewards in IPFS logs,
    which is more accurate than calculating from unclaimed amounts.
    """

    # Previous distribution frame metrics
    previous_distribution_eth: float | None = None
    previous_distribution_apy: float | None = None
    previous_net_apy: float | None = None  # previous_reward_apy + previous_bond_apy

    # Current distribution frame metrics
    current_distribution_eth: float | None = None
    current_distribution_apy: float | None = None

    # Next distribution estimates
    next_distribution_date: str | None = None  # ISO format
    next_distribution_est_eth: float | None = None

    # Lifetime totals
    lifetime_distribution_eth: float | None = None  # Sum of all frame rewards

    # Accurate lifetime APY (calculated with per-frame bond when history available)
    lifetime_reward_apy: float | None = None  # Duration-weighted avg from all frames
    lifetime_bond_apy: float | None = None  # Duration-weighted avg bond APY
    lifetime_net_apy: float | None = None  # lifetime_reward_apy + lifetime_bond_apy

    # Historical Reward APY (from IPFS distribution logs) - most accurate
    historical_reward_apy_28d: float | None = None  # Kept for backwards compat
    historical_reward_apy_ltd: float | None = None  # Lifetime (legacy)

    # Bond APY (stETH rebase appreciation)
    bond_apy: float | None = None

    # Net APY (Historical Reward APY + Bond APY)
    net_apy_28d: float | None = None  # Kept for backwards compat
    net_apy_ltd: float | None = None

    # Full frame history (only populated with --history flag)
    frames: list[DistributionFrame] | None = None

    # Bond stETH earnings (estimated from stETH rebasing)
    previous_bond_eth: float | None = None
    current_bond_eth: float | None = None
    lifetime_bond_eth: float | None = None

    # Historical APR values used for each frame (from Lido subgraph)
    previous_bond_apr: float | None = None  # APR used for previous frame
    current_bond_apr: float | None = None  # APR used for current frame

    # Track whether historical APR was used (vs fallback to current)
    uses_historical_apr: bool = False

    # Net total stETH (Rewards + Bond)
    previous_net_total_eth: float | None = None
    current_net_total_eth: float | None = None
    lifetime_net_total_eth: float | None = None

    # Legacy fields (deprecated, kept for backwards compatibility)
    reward_apy_7d: float | None = None
    reward_apy_28d: float | None = None
    net_apy_7d: float | None = None


class StrikeSummary(BaseModel):
    """Summary of strikes for an operator."""

    total_validators_with_strikes: int = 0
    validators_at_risk: int = 0  # Validators with 3+ strikes (ejection eligible)
    validators_near_ejection: int = 0  # Validators with 2 strikes (one away from ejection)
    total_strikes: int = 0
    max_strikes: int = 0  # Highest strike count on any single validator


class HealthStatus(BaseModel):
    """Overall health status for an operator."""

    bond_healthy: bool = True
    bond_deficit_eth: Decimal = Decimal(0)
    stuck_validators_count: int = 0
    slashed_validators_count: int = 0
    validators_at_risk_count: int = 0  # Validators with balance < 32 ETH
    strikes: StrikeSummary = StrikeSummary()

    @property
    def has_issues(self) -> bool:
        """Check if there are any health issues."""
        return (
            not self.bond_healthy
            or self.stuck_validators_count > 0
            or self.slashed_validators_count > 0
            or self.validators_at_risk_count > 0
            or self.strikes.total_validators_with_strikes > 0  # Any strikes = warning
        )


class OperatorRewards(BaseModel):
    """Complete rewards summary for display."""

    model_config = {"arbitrary_types_allowed": True}

    node_operator_id: int
    manager_address: str
    reward_address: str

    # Operator type (from bond curve)
    curve_id: int = 0  # 0=Permissionless, 1=ICS/Legacy EA
    operator_type: str = "Permissionless"  # Human-readable type

    # Bond information
    current_bond_eth: Decimal
    required_bond_eth: Decimal
    excess_bond_eth: Decimal

    # Rewards information
    cumulative_rewards_shares: int
    cumulative_rewards_eth: Decimal
    distributed_shares: int
    distributed_eth: Decimal
    unclaimed_shares: int
    unclaimed_eth: Decimal

    # Total claimable
    total_claimable_eth: Decimal

    # Validator counts (from on-chain)
    total_validators: int
    active_validators: int
    exited_validators: int

    # Validator details (from beacon chain, optional)
    validator_details: list[Any] = []  # list[ValidatorInfo]
    validators_by_status: dict[str, int] | None = None
    avg_effectiveness: float | None = None

    # APY metrics (optional, requires detailed lookup)
    apy: APYMetrics | None = None

    # Operator activation date (from earliest validator activation)
    active_since: datetime | None = None

    # Health status (optional, requires detailed lookup)
    health: HealthStatus | None = None

    # Withdrawal history (optional, populated with --history flag)
    withdrawals: list[WithdrawalEvent] | None = None
