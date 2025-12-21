"""Lido protocol API for stETH APR and other metrics."""

import httpx

from ..core.config import get_settings
from .cache import cached

LIDO_API_BASE = "https://eth-api.lido.fi/v1"
LIDO_SUBGRAPH_ID = "Sxx812XgeKyzQPaBpR5YZWmGV5fZuBaPdh7DFhzSwiQ"


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
                    return {
                        "apr": float(data.get("data", {}).get("smaApr", 0)),
                        "timestamp": data.get("data", {}).get("timeUnix"),
                    }
            except Exception:
                pass

        return {"apr": None, "timestamp": None}

    @cached(ttl=3600)  # Cache for 1 hour
    async def get_historical_apr_data(self) -> list[dict]:
        """Fetch historical APR data from Lido subgraph.

        Returns list of {block, apr, blockTime} sorted by block ascending.
        Returns empty list if API key not configured or query fails.
        """
        settings = get_settings()
        if not settings.thegraph_api_key:
            return []

        # Query in descending order to get most recent 1000 entries
        # (CSM frames are at blocks 21M+, we need recent data)
        query = """
        {
          totalRewards(first: 1000, orderBy: block, orderDirection: desc) {
            apr
            block
            blockTime
          }
        }
        """

        endpoint = f"https://gateway-arbitrum.network.thegraph.com/api/{settings.thegraph_api_key}/subgraphs/id/{LIDO_SUBGRAPH_ID}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    endpoint,
                    json={"query": query},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("data", {}).get("totalRewards", [])
                    # Reverse to get ascending order (oldest to newest) for binary search
                    return list(reversed(results))
            except Exception:
                pass

        return []

    def get_apr_for_block(self, apr_data: list[dict], target_block: int) -> float | None:
        """Find the APR for a specific block number.

        Returns the APR from the oracle report closest to (but not after) target_block.
        """
        if not apr_data:
            return None

        # Find the closest report at or before target_block
        closest = None
        for entry in apr_data:
            block = int(entry["block"])
            if block <= target_block:
                closest = entry
            else:
                break  # apr_data is sorted ascending

        return float(closest["apr"]) if closest else None
