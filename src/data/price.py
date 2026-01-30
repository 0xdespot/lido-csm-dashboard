"""Price fetching from CoinGecko API."""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Cache ETH price for 5 minutes
_price_cache: dict = {"eth_usd": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes


async def get_eth_price() -> float | None:
    """Fetch current ETH price in USD from CoinGecko.

    Returns:
        ETH price in USD, or None if fetch fails
    """
    global _price_cache

    # Check cache
    now = time.time()
    if _price_cache["eth_usd"] is not None and (now - _price_cache["timestamp"]) < CACHE_TTL:
        return _price_cache["eth_usd"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "ethereum", "vs_currencies": "usd"},
            )
            if response.status_code == 200:
                data = response.json()
                price = data.get("ethereum", {}).get("usd")
                if price:
                    _price_cache["eth_usd"] = float(price)
                    _price_cache["timestamp"] = now
                    logger.info(f"Fetched ETH price: ${price}")
                    return float(price)
    except Exception as e:
        logger.warning(f"Failed to fetch ETH price: {e}")

    # Return cached value if available (even if stale)
    return _price_cache["eth_usd"]
