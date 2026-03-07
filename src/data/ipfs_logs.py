"""IPFS distribution log fetching with persistent caching."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

from ..core.config import get_settings

logger = logging.getLogger(__name__)


# Ethereum Beacon Chain genesis timestamp (Dec 1, 2020 12:00:23 UTC)
BEACON_GENESIS = 1606824023


def epoch_to_datetime(epoch: int) -> datetime:
    """Convert beacon chain epoch to datetime.

    Each epoch is 32 slots * 12 seconds = 384 seconds.
    """
    timestamp = BEACON_GENESIS + (epoch * 384)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


@dataclass
class FrameData:
    """Data from a single distribution frame."""

    start_epoch: int
    end_epoch: int
    log_cid: str
    block_number: int
    distributed_rewards: int  # For specific operator, in wei
    validator_count: int  # Number of validators for operator in this frame


class IPFSLogProvider:
    """Fetches and caches historical distribution logs from IPFS."""

    # Rate limiting: minimum seconds between gateway requests
    MIN_REQUEST_INTERVAL = 1.0

    def __init__(self, cache_dir: Path | None = None):
        self.settings = get_settings()
        # Use configurable gateways from settings (comma-separated)
        self.gateways = [g.strip() for g in self.settings.ipfs_gateways.split(",") if g.strip()]
        self.cache_dir = cache_dir or Path.home() / ".cache" / "csm-dashboard" / "ipfs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_time = 0.0
        self._rate_limit_lock = asyncio.Lock()

    def _get_cache_path(self, cid: str) -> Path:
        """Get the cache file path for a CID."""
        return self.cache_dir / f"{cid}.json"

    def _load_from_cache(self, cid: str) -> dict | None:
        """Load log data from local cache if available."""
        cache_path = self._get_cache_path(cid)
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                # Corrupted cache, remove it
                cache_path.unlink(missing_ok=True)
        return None

    def _save_to_cache(self, cid: str, data: dict) -> None:
        """Save log data to local cache."""
        cache_path = self._get_cache_path(cid)
        try:
            with open(cache_path, "w") as f:
                json.dump(data, f)
        except OSError:
            pass  # Cache write failure is non-fatal

    async def _rate_limit(self) -> None:
        """Ensure minimum interval between IPFS gateway requests (async-safe).

        Claim the next available time slot while holding the lock, then sleep
        outside the lock so other coroutines can schedule their slots concurrently.
        """
        async with self._rate_limit_lock:
            now = time.time()
            next_slot = max(now, self._last_request_time + self.MIN_REQUEST_INTERVAL)
            self._last_request_time = next_slot
            wait_time = next_slot - now

        if wait_time > 0:
            await asyncio.sleep(wait_time)

    async def fetch_log(self, cid: str) -> dict | None:
        """
        Fetch and parse a distribution log from IPFS.

        Checks local cache first, then tries IPFS gateways.
        Returns None if fetch fails.
        """
        # Check cache first
        cached = self._load_from_cache(cid)
        if cached is not None:
            return cached

        # Rate limit gateway requests (async-safe)
        await self._rate_limit()

        # Try each gateway
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for gateway in self.gateways:
                try:
                    url = f"{gateway}{cid}"
                    response = await client.get(url)
                    if response.status_code == 200:
                        try:
                            data = response.json()
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse IPFS JSON from {gateway}: {e}")
                            continue
                        # The IPFS log is wrapped in a list, unwrap it
                        if isinstance(data, list) and len(data) == 1:
                            data = data[0]
                        # Cache the successful result
                        self._save_to_cache(cid, data)
                        return data
                except Exception as e:
                    logger.debug(f"IPFS gateway {gateway} failed for CID {cid}: {e}")
                    continue  # Try next gateway

        logger.warning(f"All IPFS gateways failed for CID {cid}")
        return None

    def get_operator_frame_rewards(self, log_data: dict, operator_id: int) -> int | None:
        """
        Extract operator's distributed_rewards for a frame.

        Returns rewards in wei (shares), or None if operator not in frame.

        Note: The IPFS log field name changed from "distributed" to "distributed_rewards"
        around Dec 2025. We check both for backwards compatibility.
        """
        operators = log_data.get("operators", {})
        op_key = str(operator_id)

        if op_key not in operators:
            return None

        op_data = operators[op_key]
        # Handle both new and old field names for backwards compatibility
        rewards = op_data.get("distributed_rewards")
        if rewards is None:
            rewards = op_data.get("distributed")  # Fallback to old field name
        return rewards if rewards is not None else 0

    def get_frame_info(self, log_data: dict) -> tuple[int, int]:
        """
        Extract frame epoch range from log data.

        Returns (start_epoch, end_epoch).
        """
        frame = log_data.get("frame", [0, 0])
        if not isinstance(frame, list) or len(frame) < 2:
            return (0, 0)
        return (frame[0], frame[1])

    def get_operator_validator_count(self, log_data: dict, operator_id: int) -> int:
        """
        Get the number of validators for an operator in a frame.

        Returns the count of validators, or 0 if operator not in frame.
        """
        operators = log_data.get("operators", {})
        op_key = str(operator_id)

        if op_key not in operators:
            return 0

        op_data = operators[op_key]
        validators = op_data.get("validators", {})
        return len(validators)

    async def get_operator_history(
        self,
        operator_id: int,
        log_cids: list[dict],  # List of {block, logCid} from events
    ) -> list[FrameData]:
        """
        Fetch all historical frame data for an operator.

        Args:
            operator_id: The operator ID to look up
            log_cids: List of {block, logCid} dicts from DistributionLogUpdated events

        Returns:
            List of FrameData objects, sorted by epoch (oldest first)
        """
        frames = []

        for entry in log_cids:
            cid = entry["logCid"]
            block = entry["block"]

            log_data = await self.fetch_log(cid)
            if log_data is None:
                continue

            rewards = self.get_operator_frame_rewards(log_data, operator_id)
            if rewards is None:
                # Operator not in this frame (may have joined later)
                continue

            start_epoch, end_epoch = self.get_frame_info(log_data)
            validator_count = self.get_operator_validator_count(log_data, operator_id)

            frames.append(
                FrameData(
                    start_epoch=start_epoch,
                    end_epoch=end_epoch,
                    log_cid=cid,
                    block_number=block,
                    distributed_rewards=rewards,
                    validator_count=validator_count,
                )
            )

        # Sort by epoch (oldest first)
        frames.sort(key=lambda f: f.start_epoch)
        return frames

    def calculate_frame_duration_days(self, frame: FrameData) -> float:
        """Calculate the duration of a frame in days."""
        # Each epoch is 6.4 minutes (384 seconds = 32 slots * 12 seconds)
        epochs = frame.end_epoch - frame.start_epoch
        minutes = epochs * 6.4
        return minutes / (60 * 24)

    def calculate_historical_apy(
        self,
        frames: list[FrameData],
        bond_eth: Decimal,
        periods: list[int] | None = None,
    ) -> dict[str, float | None]:
        """
        Calculate APY from historical frame data.

        Args:
            frames: List of FrameData objects (oldest first)
            bond_eth: Current bond in ETH (used for all periods)
            periods: List of day counts to calculate APY for (default: [28, None] for 28d and LTD)

        Returns:
            Dict mapping period name to APY percentage (e.g., {"28d": 3.92, "ltd": 4.10})

        Note:
            For lifetime APY, only frames with non-zero rewards are included. This avoids
            artificially low APY for operators who had a ramp-up period with no rewards.
        """
        if periods is None:
            periods = [28, None]  # 28-day and lifetime

        if not frames or bond_eth <= 0:
            return {self._period_name(p): None for p in periods}

        results = {}

        for period in periods:
            if period is None:
                # Lifetime: only frames where operator earned rewards
                # This avoids ramp-up periods with 0 rewards skewing the APY
                selected_frames = [f for f in frames if f.distributed_rewards > 0]
            else:
                # Select frames within the period
                # Work backwards from most recent frame
                total_days = 0.0
                selected_frames = []
                for frame in reversed(frames):
                    frame_days = self.calculate_frame_duration_days(frame)
                    if total_days + frame_days <= period * 1.5:  # Allow some buffer
                        selected_frames.insert(0, frame)
                        total_days += frame_days
                    if total_days >= period:
                        break

            if not selected_frames:
                results[self._period_name(period)] = None
                continue

            # Sum rewards and calculate total days
            total_rewards_wei = sum(f.distributed_rewards for f in selected_frames)
            total_days = sum(self.calculate_frame_duration_days(f) for f in selected_frames)

            if total_days <= 0:
                results[self._period_name(period)] = None
                continue

            # Convert rewards to ETH
            total_rewards_eth = Decimal(total_rewards_wei) / Decimal(10**18)

            # Annualize: (rewards / bond) * (365 / days) * 100
            # Keep calculation in Decimal for precision, convert to float only at the end
            apy = (total_rewards_eth / bond_eth) * Decimal(365) / Decimal(total_days) * Decimal(100)

            results[self._period_name(period)] = round(float(apy), 2)

        return results

    def _period_name(self, period: int | None) -> str:
        """Convert period days to display name."""
        if period is None:
            return "ltd"
        return f"{period}d"

    def clear_cache(self) -> None:
        """Clear all cached IPFS logs."""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink(missing_ok=True)
