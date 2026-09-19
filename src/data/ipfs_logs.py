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


def _is_valid_frame(frame_obj: object) -> bool:
    """Shape check for a single frame object.

    Only the fields the parser actually relies on are checked; unknown extra
    keys are fine, since the log format has gained fields over time.
    """
    if not isinstance(frame_obj, dict):
        return False

    frame = frame_obj.get("frame")
    if not isinstance(frame, list) or len(frame) < 2:
        return False
    # bool is an int subclass but is never a valid epoch.
    if not all(isinstance(e, int) and not isinstance(e, bool) for e in frame[:2]):
        return False

    return isinstance(frame_obj.get("operators"), dict)


def normalize_log_frames(data: object) -> list[dict]:
    """Return the frame objects in a distribution log, whatever its format.

    Two formats are in circulation:

    * legacy — the frame object sits at the top level, one frame per CID;
    * versioned — ``{"_ver": 1, "frames": [<frame>, ...]}``, adopted mid-2026,
      where the inner frame keeps the legacy schema.

    Returns ``[]`` for anything unrecognised. Every frame in the list is
    returned, since the versioned format permits more than one per CID and
    dropping the extras would silently lose distributions.
    """
    if not isinstance(data, dict):
        return []

    if isinstance(data.get("frames"), list):
        return [f for f in data["frames"] if isinstance(f, dict)]

    if "frame" in data:
        return [data]

    return []


def is_valid_log_payload(data: object) -> bool:
    """Minimal shape check for a distribution log fetched from IPFS.

    Guards against a gateway returning a truncated, wrapped, or error payload.
    Such a payload makes ``get_frame_info`` fall back to ``(0, 0)``, which in
    turn produced a zero-length frame downstream — so rejecting it here keeps a
    single bad response from being cached to disk and becoming sticky.
    """
    frames = normalize_log_frames(data)
    return bool(frames) and all(_is_valid_frame(f) for f in frames)


class IPFSLogProvider:
    """Fetches and caches historical distribution logs from IPFS."""

    # Rate limiting: minimum seconds between gateway requests
    MIN_REQUEST_INTERVAL = 1.0

    def __init__(self, cache_dir: Path | None = None):
        self.settings = get_settings()
        # Use configurable gateways from settings (comma-separated)
        self.gateways = [g.strip() for g in self.settings.ipfs_gateways.split(",") if g.strip()]
        self.cache_dir = cache_dir or self.settings.ipfs_cache_dir
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
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                # Corrupted cache, remove it
                cache_path.unlink(missing_ok=True)
                return None
            if not is_valid_log_payload(data):
                # Written before this validation existed, or by a bad gateway.
                # Drop it so the next fetch can replace it.
                logger.warning(f"Discarding malformed cached IPFS log for CID {cid}")
                cache_path.unlink(missing_ok=True)
                return None
            return data
        return None

    def _save_to_cache(self, cid: str, data: dict) -> None:
        """Save log data to local cache."""
        if not is_valid_log_payload(data):
            logger.warning(f"Refusing to cache malformed IPFS log for CID {cid}")
            return
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
                    if response.status_code != 200:
                        # Previously skipped in silence, so a fleet-wide 429
                        # looked identical to a missing CID.
                        logger.warning(
                            f"IPFS gateway {gateway} returned HTTP "
                            f"{response.status_code} for CID {cid}"
                        )
                    if response.status_code == 200:
                        try:
                            data = response.json()
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse IPFS JSON from {gateway}: {e}")
                            continue
                        # The IPFS log is wrapped in a list, unwrap it
                        if isinstance(data, list) and len(data) == 1:
                            data = data[0]
                        if not is_valid_log_payload(data):
                            # Truncated or error payload — try the next gateway
                            # rather than accepting and caching it.
                            logger.warning(
                                f"Malformed IPFS log from {gateway} for CID {cid}; "
                                "trying next gateway"
                            )
                            continue
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
        if rewards is None:
            return 0
        # The versioned log format quotes these wei amounts as strings, while
        # the legacy format used ints. Coerce, or the value flows into
        # `sum(...)` downstream and raises a TypeError that the caller's broad
        # `except Exception` turns into a silently empty history.
        try:
            return int(rewards)
        except (TypeError, ValueError):
            logger.warning(
                f"Unparseable distributed_rewards for operator {operator_id}: {rewards!r}"
            )
            return 0

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
    ) -> tuple[list[FrameData], int]:
        """
        Fetch all historical frame data for an operator.

        Args:
            operator_id: The operator ID to look up
            log_cids: List of {block, logCid} dicts from DistributionLogUpdated events

        Returns:
            Tuple of (list of FrameData sorted by epoch oldest first, count of failed CID fetches)
        """
        frames = []
        failed_count = 0

        for entry in log_cids:
            cid = entry["logCid"]
            block = entry["block"]

            log_data = await self.fetch_log(cid)
            if log_data is None:
                failed_count += 1
                continue

            # A versioned log can bundle several frames under one CID; the
            # legacy format normalizes to a single-element list.
            for frame_obj in normalize_log_frames(log_data):
                rewards = self.get_operator_frame_rewards(frame_obj, operator_id)
                if rewards is None:
                    # Operator not in this frame (may have joined later)
                    continue

                start_epoch, end_epoch = self.get_frame_info(frame_obj)
                validator_count = self.get_operator_validator_count(frame_obj, operator_id)

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

        if failed_count > 0:
            logger.warning(
                f"Failed to fetch {failed_count}/{len(log_cids)} "
                f"distribution logs from IPFS"
            )

        # Sort by epoch (oldest first)
        frames.sort(key=lambda f: f.start_epoch)
        return frames, failed_count

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
