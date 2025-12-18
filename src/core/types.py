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


class APYMetrics(BaseModel):
    """APY calculations for an operator.

    Note: Validator APY (consensus rewards) is NOT included because CSM operators
    don't receive those rewards directly - they go to Lido protocol and are
    redistributed via CSM reward distributions (captured in reward_apy).

    Historical APY is calculated from actual distributed rewards in IPFS logs,
    which is more accurate than calculating from unclaimed amounts.
    """

    # Historical Reward APY (from IPFS distribution logs) - most accurate
    historical_reward_apy_28d: float | None = None  # Last ~28 days (1 frame)
    historical_reward_apy_ltd: float | None = None  # Lifetime

    # Bond APY (stETH rebase appreciation)
    bond_apy: float | None = None

    # Net APY (Historical Reward APY + Bond APY)
    net_apy_28d: float | None = None
    net_apy_ltd: float | None = None

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
