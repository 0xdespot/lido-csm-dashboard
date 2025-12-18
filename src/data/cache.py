"""Simple in-memory cache with TTL support."""

import hashlib
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable

from ..core.config import get_settings


class SimpleCache:
    """Simple in-memory cache with TTL. Safe for single-threaded async but not thread-safe."""

    def __init__(self, default_ttl: int | None = None):
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._default_ttl = default_ttl or get_settings().cache_ttl_seconds

    def get(self, key: str) -> Any | None:
        """Get value from cache if not expired."""
        if key in self._cache:
            value, expiry = self._cache[key]
            if datetime.now() < expiry:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache with TTL."""
        expiry = datetime.now() + timedelta(seconds=ttl or self._default_ttl)
        self._cache[key] = (value, expiry)

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()


# Global cache instance
_cache = SimpleCache()


def cached(ttl: int | None = None) -> Callable:
    """Decorator for caching async function results."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Create cache key from function name and arguments
            # Use repr() for proper tuple/list representation to avoid collisions
            key_data = f"{func.__module__}.{func.__name__}:{repr(args)}:{repr(sorted(kwargs.items()))}"
            cache_key = hashlib.md5(key_data.encode()).hexdigest()

            cached_result = _cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            result = await func(*args, **kwargs)
            _cache.set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator


def get_cache() -> SimpleCache:
    """Get the global cache instance."""
    return _cache
