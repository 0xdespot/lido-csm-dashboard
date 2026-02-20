"""Lido protocol API for stETH APR and other metrics."""

import logging

import httpx

from .cache import cached

logger = logging.getLogger(__name__)

LIDO_API_BASE = "https://eth-api.lido.fi/v1"


class LidoAPIProvider:
    """Fetches data from Lido's public API."""

    @cached(ttl=3600)  # Cache for 1 hour
    async def get_steth_apr(self) -> dict:
        """
        Get current stETH APR from Lido API.

        Returns 7-day SMA (simple moving average) APR.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    f"{LIDO_API_BASE}/protocol/steth/apr/sma"
                )

                if response.status_code == 200:
                    data = response.json()
                    # Handle case where data["data"] could be explicitly None
                    data_obj = data.get("data") or {}
                    return {
                        "apr": float(data_obj.get("smaApr", 0) or 0),
                        "timestamp": data_obj.get("timeUnix"),
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch stETH APR from Lido API: {e}")

        return {"apr": None, "timestamp": None}

    def get_apr_for_block(self, apr_data: list[dict], target_block: int) -> float | None:
        """Find the APR for a specific block number.

        Returns the APR from the oracle report closest to (but not after) target_block.
        """
        if not apr_data:
            return None

        # Find the closest report at or before target_block
        closest = None
        for entry in apr_data:
            try:
                block = int(entry.get("block", 0))
            except (ValueError, TypeError):
                continue
            if block <= target_block:
                closest = entry
            else:
                break  # apr_data is sorted ascending

        if closest:
            try:
                return float(closest.get("apr", 0))
            except (ValueError, TypeError):
                return None
        return None

    def get_average_apr_for_range(
        self, apr_data: list[dict], start_timestamp: int, end_timestamp: int
    ) -> float | None:
        """Calculate average APR for a time range.

        Averages all APR values from oracle reports within the given timestamp range.
        Falls back to the closest APR before the range if no reports fall within.

        Args:
            apr_data: List of {block, apr, blockTime} sorted by block ascending
            start_timestamp: Unix timestamp for range start
            end_timestamp: Unix timestamp for range end

        Returns:
            Average APR as a percentage, or None if no data available
        """
        if not apr_data:
            return None

        # Find all APR reports within the time range
        reports_in_range = []
        closest_before = None

        for entry in apr_data:
            try:
                block_time = int(entry.get("blockTime", 0))
            except (ValueError, TypeError):
                continue
            if block_time < start_timestamp:
                closest_before = entry  # Keep track of most recent before range
            elif block_time <= end_timestamp:
                reports_in_range.append(entry)
            else:
                break  # Past the range, stop searching

        if reports_in_range:
            # Average all reports within the range
            valid_aprs = []
            for r in reports_in_range:
                try:
                    valid_aprs.append(float(r.get("apr", 0)))
                except (ValueError, TypeError):
                    continue
            if valid_aprs:
                return sum(valid_aprs) / len(valid_aprs)
        elif closest_before:
            # No reports in range, use the closest one before
            try:
                return float(closest_before.get("apr", 0))
            except (ValueError, TypeError):
                pass

        return None
