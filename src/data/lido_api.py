"""Lido protocol API for stETH APR and other metrics."""

import httpx

from .cache import cached

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
                    return {
                        "apr": float(data.get("data", {}).get("smaApr", 0)),
                        "timestamp": data.get("data", {}).get("timeUnix"),
                    }
            except Exception:
                pass

        return {"apr": None, "timestamp": None}
