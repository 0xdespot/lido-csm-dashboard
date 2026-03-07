"""Simple in-memory cache with TTL support and LRU eviction."""

import hashlib
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable

from ..core.config import get_settings

logger = logging.getLogger(__name__)

# Default maximum cache entries to prevent unbounded memory growth
DEFAULT_MAX_SIZE = 1000

# Sentinel distinguishing "not in cache" from "cached value is None"
_MISSING = object()


class SimpleCache:
    """
    Simple in-memory cache with TTL and LRU eviction.

    Safe for single-threaded async but not thread-safe.
    Uses OrderedDict for LRU eviction when max_size is reached.
    """

    def __init__(self, default_ttl: int | None = None, max_size: int = DEFAULT_MAX_SIZE):
        self._cache: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()
        self._default_ttl = default_ttl or get_settings().cache_ttl_seconds
        self._max_size = max_size

    def get(self, key: str) -> Any:
        """Get value from cache if not expired. Returns _MISSING if not found or expired."""
        if key in self._cache:
            value, expiry = self._cache[key]
            if datetime.now() < expiry:
                # Move to end to mark as recently used
                self._cache.move_to_end(key)
                return value
            # Expired - remove it
            del self._cache[key]
        return _MISSING

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache with TTL. Evicts LRU entries if at max size."""
        # If key exists, remove it first (will be re-added at end)
        if key in self._cache:
            del self._cache[key]

        # Evict oldest entries if at max size
        while len(self._cache) >= self._max_size:
            oldest_key, _ = self._cache.popitem(last=False)
            logger.debug(f"Cache eviction: removed {oldest_key[:16]}...")

        expiry = datetime.now() + timedelta(seconds=ttl or self._default_ttl)
        self._cache[key] = (value, expiry)

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        now = datetime.now()
        expired_keys = [
            key for key, (_, expiry) in self._cache.items() if now >= expiry
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    @property
    def size(self) -> int:
        """Current number of entries in cache."""
        return len(self._cache)


# Global cache instance
_cache = SimpleCache()


def cached(ttl: int | None = None) -> Callable:
    """Decorator for caching async function results."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Create cache key from function name and arguments
            # Skip 'self' in args to allow cache sharing across instances (for methods)
            # Detect 'self' by checking if first arg is an instance with the decorated method
            cache_args = args
            if args and hasattr(args[0], func.__name__):
                # First arg is likely 'self' - skip it for cache key
                cache_args = args[1:]
            key_data = f"{func.__module__}.{func.__name__}:{repr(cache_args)}:{repr(sorted(kwargs.items()))}"
            cache_key = hashlib.md5(key_data.encode()).hexdigest()

            cached_result = _cache.get(cache_key)
            if cached_result is not _MISSING:
                return cached_result

            result = await func(*args, **kwargs)
            _cache.set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator


def get_cache() -> SimpleCache:
    """Get the global cache instance."""
    return _cache
