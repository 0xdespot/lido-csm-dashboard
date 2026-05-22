"""Unit tests for OnChainDataProvider event scanning."""

import asyncio
from unittest.mock import MagicMock

from src.data.onchain import OnChainDataProvider


def _make_provider(block_number, get_logs):
    """Build an OnChainDataProvider without touching the network."""
    provider = OnChainDataProvider.__new__(OnChainDataProvider)
    provider._data_warnings = []
    provider.w3 = MagicMock()
    provider.w3.eth.block_number = block_number
    provider.csfeedistributor = MagicMock()
    provider.csfeedistributor.events.DistributionLogUpdated.get_logs = get_logs
    return provider


def test_query_events_chunked_clean_scan_reports_completed():
    """A scan that covers the full range without failures reports completed."""
    provider = _make_provider(block_number=21_000_000, get_logs=lambda **kw: [])

    events, completed = asyncio.run(provider._query_events_chunked(20_990_000))

    assert events == []
    assert completed is True
    assert provider._data_warnings == []


def test_query_events_chunked_failed_scan_reports_incomplete(monkeypatch):
    """A scan that hits the consecutive-failure abort reports not completed."""

    # Skip the exponential-backoff sleeps so the test runs fast.
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr("src.data.onchain.asyncio.sleep", _no_sleep)

    def _always_fail(**kwargs):
        raise RuntimeError("RPC rejected eth_getLogs")

    provider = _make_provider(block_number=21_000_000, get_logs=_always_fail)

    events, completed = asyncio.run(provider._query_events_chunked(20_000_000))

    assert events == []
    assert completed is False
    assert any("stopped early" in w for w in provider._data_warnings)
