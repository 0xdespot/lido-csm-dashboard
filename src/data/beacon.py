"""Beacon chain data fetching via beaconcha.in API."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

import httpx

from ..core.config import get_settings
from .cache import cached

# Beacon Chain constants
BEACON_GENESIS = datetime(2020, 12, 1, 12, 0, 23, tzinfo=timezone.utc)
SECONDS_PER_EPOCH = 32 * 12  # 384 seconds (32 slots × 12 seconds per slot)


def epoch_to_datetime(epoch: int) -> datetime:
    """Convert beacon chain epoch to datetime."""
    return BEACON_GENESIS + timedelta(seconds=epoch * SECONDS_PER_EPOCH)


def get_earliest_activation(validators: list["ValidatorInfo"]) -> datetime | None:
    """Get the earliest activation date from a list of validators."""
    epochs = [v.activation_epoch for v in validators if v.activation_epoch is not None]
    if not epochs:
        return None
    return epoch_to_datetime(min(epochs))


class ValidatorStatus(str, Enum):
    """Validator lifecycle status on the beacon chain."""

    PENDING_INITIALIZED = "pending_initialized"
    PENDING_QUEUED = "pending_queued"
    ACTIVE_ONGOING = "active_ongoing"
    ACTIVE_EXITING = "active_exiting"
    ACTIVE_SLASHED = "active_slashed"
    EXITED_UNSLASHED = "exited_unslashed"
    EXITED_SLASHED = "exited_slashed"
    WITHDRAWAL_POSSIBLE = "withdrawal_possible"
    WITHDRAWAL_DONE = "withdrawal_done"
    UNKNOWN = "unknown"

    @classmethod
    def from_beaconcha(cls, status: str) -> "ValidatorStatus":
        """Convert beaconcha.in status string to enum."""
        status_map = {
            "pending": cls.PENDING_QUEUED,
            "active_online": cls.ACTIVE_ONGOING,
            "active_offline": cls.ACTIVE_ONGOING,
            "active": cls.ACTIVE_ONGOING,
            "exiting_online": cls.ACTIVE_EXITING,
            "exiting_offline": cls.ACTIVE_EXITING,
            "exiting": cls.ACTIVE_EXITING,
            "slashing_online": cls.ACTIVE_SLASHED,
            "slashing_offline": cls.ACTIVE_SLASHED,
            "slashing": cls.ACTIVE_SLASHED,
            "slashed": cls.EXITED_SLASHED,
            "exited": cls.EXITED_UNSLASHED,
            "withdrawable": cls.WITHDRAWAL_POSSIBLE,
            "withdrawn": cls.WITHDRAWAL_DONE,
        }
        return status_map.get(status.lower(), cls.UNKNOWN)

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        names = {
            self.PENDING_INITIALIZED: "Pending (Init)",
            self.PENDING_QUEUED: "Pending",
            self.ACTIVE_ONGOING: "Active",
            self.ACTIVE_EXITING: "Exiting",
            self.ACTIVE_SLASHED: "Slashed",
            self.EXITED_UNSLASHED: "Exited",
            self.EXITED_SLASHED: "Slashed & Exited",
            self.WITHDRAWAL_POSSIBLE: "Withdrawable",
            self.WITHDRAWAL_DONE: "Withdrawn",
            self.UNKNOWN: "Unknown",
        }
        return names.get(self, "Unknown")

    @property
    def is_active(self) -> bool:
        """Check if validator is currently active."""
        return self in (self.ACTIVE_ONGOING, self.ACTIVE_EXITING, self.ACTIVE_SLASHED)

    @property
    def is_exited(self) -> bool:
        """Check if validator has exited."""
        return self in (
            self.EXITED_UNSLASHED,
            self.EXITED_SLASHED,
            self.WITHDRAWAL_POSSIBLE,
            self.WITHDRAWAL_DONE,
        )


class ValidatorInfo:
    """Information about a single validator."""

    def __init__(
        self,
        pubkey: str,
        index: int | None = None,
        status: ValidatorStatus = ValidatorStatus.UNKNOWN,
        balance_gwei: int = 0,
        effectiveness: float | None = None,
        activation_epoch: int | None = None,
        exit_epoch: int | None = None,
    ):
        self.pubkey = pubkey
        self.index = index
        self.status = status
        self.balance_gwei = balance_gwei
        self.effectiveness = effectiveness
        self.activation_epoch = activation_epoch
        self.exit_epoch = exit_epoch

    @property
    def balance_eth(self) -> Decimal:
        """Balance in ETH."""
        return Decimal(self.balance_gwei) / Decimal(10**9)

    @property
    def at_risk(self) -> bool:
        """
        Check if validator is at risk due to low balance.

        A validator with effective balance < 32 ETH may face withdrawal penalties
        when exiting, as the difference will be confiscated from the operator's bond.
        """
        # Only active validators can be "at risk" in this sense
        if not self.status.is_active:
            return False
        # 32 ETH = 32_000_000_000 gwei
        return self.balance_gwei < 32_000_000_000

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "pubkey": self.pubkey,
            "index": self.index,
            "status": self.status.value,
            "status_display": self.status.display_name,
            "balance_eth": float(self.balance_eth),
            "effectiveness": self.effectiveness,
            "activation_epoch": self.activation_epoch,
            "exit_epoch": self.exit_epoch,
            "at_risk": self.at_risk,
        }


class BeaconDataProvider:
    """Fetches validator data from beaconcha.in API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.beacon_api_url.rstrip("/")

    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests, including API key if configured."""
        headers = {"accept": "application/json"}
        if self.settings.beacon_api_key:
            headers["apikey"] = self.settings.beacon_api_key
        return headers

    @cached(ttl=300)  # Cache for 5 minutes
    async def get_validators_by_pubkeys(
        self, pubkeys: list[str]
    ) -> list[ValidatorInfo]:
        """
        Fetch validator info for multiple pubkeys.

        beaconcha.in supports comma-separated pubkeys (up to 100).
        """
        if not pubkeys:
            return []

        validators = []
        batch_size = 100  # beaconcha.in limit

        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(0, len(pubkeys), batch_size):
                batch = pubkeys[i : i + batch_size]
                pubkeys_param = ",".join(batch)

                try:
                    response = await client.get(
                        f"{self.base_url}/validator/{pubkeys_param}",
                        headers=self._get_headers(),
                    )

                    if response.status_code == 200:
                        data = response.json().get("data", [])
                        # API returns single object if only one validator
                        if isinstance(data, dict):
                            data = [data]

                        for v in data:
                            validators.append(self._parse_validator(v))
                    elif response.status_code == 404:
                        # Validators not found - create placeholder entries
                        for pubkey in batch:
                            validators.append(
                                ValidatorInfo(
                                    pubkey=pubkey,
                                    status=ValidatorStatus.PENDING_INITIALIZED,
                                )
                            )
                except Exception:
                    # On error, add unknown status for this batch
                    for pubkey in batch:
                        validators.append(
                            ValidatorInfo(pubkey=pubkey, status=ValidatorStatus.UNKNOWN)
                        )

        return validators

    def _parse_validator(self, data: dict) -> ValidatorInfo:
        """Parse beaconcha.in validator response."""
        return ValidatorInfo(
            pubkey=data.get("pubkey", ""),
            index=data.get("validatorindex"),
            status=ValidatorStatus.from_beaconcha(data.get("status", "unknown")),
            balance_gwei=data.get("balance", 0),
            effectiveness=data.get("effectiveness"),
            activation_epoch=data.get("activationepoch"),
            exit_epoch=data.get("exitepoch") if data.get("exitepoch") is not None and data.get("exitepoch") >= 0 else None,
        )

    @cached(ttl=300)
    async def get_validator_performance(
        self, validator_index: int
    ) -> dict | None:
        """Get detailed performance metrics for a validator."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/validator/{validator_index}/performance",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    return response.json().get("data")
            except Exception:
                pass

        return None

    @cached(ttl=300)
    async def get_validator_income(
        self, validator_indices: list[int], days: int = 28
    ) -> dict:
        """
        Fetch validator income for a period.

        Uses the /validator/{indices}/incomedetailhistory endpoint.
        Returns total consensus rewards in ETH for the period.

        Args:
            validator_indices: List of validator indices to query
            days: Number of days of history to fetch (7 or 28)
        """
        if not validator_indices:
            return {"total_income_eth": Decimal(0), "days": days}

        total_income_gwei = 0
        batch_size = 100  # beaconcha.in limit

        # Calculate epoch limit (~225 epochs per day)
        epoch_limit = days * 225

        async with httpx.AsyncClient(timeout=60.0) as client:
            for i in range(0, len(validator_indices), batch_size):
                batch = validator_indices[i : i + batch_size]
                indices_param = ",".join(str(idx) for idx in batch)

                try:
                    response = await client.get(
                        f"{self.base_url}/validator/{indices_param}/incomedetailhistory",
                        params={"limit": epoch_limit},
                        headers=self._get_headers(),
                    )

                    if response.status_code == 200:
                        data = response.json().get("data", [])
                        # Handle single validator response (dict instead of list)
                        if isinstance(data, dict):
                            data = [data]

                        for entry in data:
                            # Each entry has income breakdown by reward type
                            # API returns: attestation_source_reward, attestation_target_reward,
                            # attestation_head_reward (not a "total" field)
                            income = entry.get("income", {})
                            if isinstance(income, dict):
                                # Sum all reward types (values are in gwei)
                                total_income_gwei += sum(income.values())
                            elif isinstance(income, int):
                                total_income_gwei += income
                except Exception:
                    # On error, continue with partial data
                    pass

        return {
            "total_income_eth": Decimal(total_income_gwei) / Decimal(10**9),
            "days": days,
        }


def aggregate_validator_status(validators: list[ValidatorInfo]) -> dict[str, int]:
    """
    Aggregate validator statuses into counts.

    Returns dict like: {"active": 198, "pending": 1, "exited": 1, "slashed": 0}
    """
    counts = {
        "active": 0,
        "pending": 0,
        "exiting": 0,
        "exited": 0,
        "slashed": 0,
        "unknown": 0,
    }

    for v in validators:
        if v.status.is_active and v.status != ValidatorStatus.ACTIVE_SLASHED:
            if v.status == ValidatorStatus.ACTIVE_EXITING:
                counts["exiting"] += 1
            else:
                counts["active"] += 1
        elif v.status in (ValidatorStatus.PENDING_INITIALIZED, ValidatorStatus.PENDING_QUEUED):
            counts["pending"] += 1
        elif v.status.is_exited:
            if v.status == ValidatorStatus.EXITED_SLASHED:
                counts["slashed"] += 1
            else:
                counts["exited"] += 1
        elif v.status == ValidatorStatus.ACTIVE_SLASHED:
            counts["slashed"] += 1
        else:
            counts["unknown"] += 1

    return counts


def calculate_avg_effectiveness(validators: list[ValidatorInfo]) -> float | None:
    """Calculate average attestation effectiveness across validators."""
    active_with_effectiveness = [
        v for v in validators if v.status.is_active and v.effectiveness is not None
    ]

    if not active_with_effectiveness:
        return None

    total = sum(v.effectiveness for v in active_with_effectiveness)
    return total / len(active_with_effectiveness)


def count_at_risk_validators(validators: list[ValidatorInfo]) -> int:
    """Count validators with balance < 32 ETH (at risk of withdrawal penalty)."""
    return sum(1 for v in validators if v.at_risk)


def count_slashed_validators(validators: list[ValidatorInfo]) -> int:
    """Count slashed validators."""
    return sum(
        1 for v in validators
        if v.status in (ValidatorStatus.ACTIVE_SLASHED, ValidatorStatus.EXITED_SLASHED)
    )
