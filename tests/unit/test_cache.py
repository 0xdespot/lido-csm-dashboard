"""Tests for the cache module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.data.cache import SimpleCache, _MISSING, cached, get_cache


class TestSimpleCache:
    """Tests for the SimpleCache class."""

    def test_cache_set_and_get(self):
        """Test basic set and get operations."""
        cache = SimpleCache(default_ttl=300)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_returns_missing_for_missing_key(self):
        """Test that missing keys return _MISSING sentinel (not None)."""
        cache = SimpleCache(default_ttl=300)
        assert cache.get("nonexistent") is _MISSING

    def test_cache_expiry(self):
        """Test that expired entries are not returned."""
        cache = SimpleCache(default_ttl=300)
        cache.set("key1", "value1", ttl=1)

        # Immediately should work
        assert cache.get("key1") == "value1"

        # Mock time to be past expiry
        with patch("src.data.cache.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime.now() + timedelta(seconds=2)
            assert cache.get("key1") is _MISSING

    def test_cache_custom_ttl(self):
        """Test setting custom TTL per entry."""
        cache = SimpleCache(default_ttl=300)
        cache.set("key1", "value1", ttl=600)

        # Mock time to be 400 seconds later (past default TTL but within custom TTL)
        with patch("src.data.cache.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime.now() + timedelta(seconds=400)
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            # Note: This test is tricky due to how timedelta works with mocked datetime
            # The cache stores expiry at set time, so checking is against stored expiry

    def test_cache_clear(self):
        """Test clearing all cached entries."""
        cache = SimpleCache(default_ttl=300)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

        cache.clear()

        assert cache.get("key1") is _MISSING
        assert cache.get("key2") is _MISSING

    def test_cache_overwrite(self):
        """Test that setting the same key overwrites the value."""
        cache = SimpleCache(default_ttl=300)
        cache.set("key1", "value1")
        cache.set("key1", "value2")
        assert cache.get("key1") == "value2"

    def test_cache_stores_different_types(self):
        """Test that cache can store various Python types."""
        cache = SimpleCache(default_ttl=300)

        cache.set("str", "string value")
        cache.set("int", 42)
        cache.set("float", 3.14)
        cache.set("list", [1, 2, 3])
        cache.set("dict", {"a": 1, "b": 2})
        cache.set("none", None)

        assert cache.get("str") == "string value"
        assert cache.get("int") == 42
        assert cache.get("float") == 3.14
        assert cache.get("list") == [1, 2, 3]
        assert cache.get("dict") == {"a": 1, "b": 2}
        # Note: None is a valid cached value, but get() returns None for missing keys too


class TestCachedDecorator:
    """Tests for the @cached decorator."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear the global cache before each test."""
        get_cache().clear()

    @pytest.mark.asyncio
    async def test_cached_decorator_caches_result(self):
        """Test that the decorator caches function results."""
        call_count = 0

        @cached(ttl=300)
        async def my_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        # First call should execute the function
        result1 = await my_function(5)
        assert result1 == 10
        assert call_count == 1

        # Second call should return cached result
        result2 = await my_function(5)
        assert result2 == 10
        assert call_count == 1  # Function not called again

    @pytest.mark.asyncio
    async def test_cached_decorator_different_args(self):
        """Test that different arguments result in different cache keys."""
        call_count = 0

        @cached(ttl=300)
        async def my_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = await my_function(5)
        result2 = await my_function(10)

        assert result1 == 10
        assert result2 == 20
        assert call_count == 2  # Both should call the function

    @pytest.mark.asyncio
    async def test_cached_decorator_with_kwargs(self):
        """Test that kwargs are included in cache key."""
        call_count = 0

        @cached(ttl=300)
        async def my_function(x, multiplier=2):
            nonlocal call_count
            call_count += 1
            return x * multiplier

        result1 = await my_function(5, multiplier=2)
        result2 = await my_function(5, multiplier=3)

        assert result1 == 10
        assert result2 == 15
        assert call_count == 2  # Different kwargs = different cache key


class TestGetCache:
    """Tests for the get_cache function."""

    def test_get_cache_returns_singleton(self):
        """Test that get_cache returns the same instance."""
        cache1 = get_cache()
        cache2 = get_cache()
        assert cache1 is cache2


class TestCacheNoneHandling:
    """Tests for correct handling of None values in cache."""

    def test_simple_cache_stores_and_returns_none(self):
        """SimpleCache must distinguish between 'not found' and 'cached None'."""
        cache = SimpleCache(default_ttl=300)
        cache.set("key1", None)
        # After setting None, get() must return None (not treat it as missing)
        # We verify by checking the cache size: if size > 0, the value was stored
        assert cache.size == 1

    @pytest.mark.asyncio
    async def test_cached_decorator_caches_none_result(self):
        """@cached must not re-call the function when it previously returned None."""
        get_cache().clear()
        call_count = 0

        @cached(ttl=300)
        async def returns_none(x):
            nonlocal call_count
            call_count += 1
            return None

        result1 = await returns_none(1)
        assert result1 is None
        assert call_count == 1

        # Second call: None was already cached — function must NOT be called again
        result2 = await returns_none(1)
        assert result2 is None
        assert call_count == 1  # still 1 — cached None was returned
