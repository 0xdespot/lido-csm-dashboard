"""Unit tests for OnChainDataProvider event scanning."""

import asyncio
from unittest.mock import MagicMock

from src.data.cache import _MISSING, get_cache
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


# ---------------------------------------------------------------------------
# get_bond_event_history — pruned-receipt handling and conditional caching
# ---------------------------------------------------------------------------


def _make_bond_provider(block_number, get_logs_by_event):
    """Build a provider with csaccounting.events mocked for bond-event scanning.

    `get_logs_by_event` is a dict {event_name: callable(**kwargs) -> list[log]}.
    Event names not in the dict yield empty results.
    """
    provider = OnChainDataProvider.__new__(OnChainDataProvider)
    provider._data_warnings = []
    provider.w3 = MagicMock()
    provider.w3.eth.block_number = block_number
    # get_block returns a fake block with a fixed timestamp
    provider.w3.eth.get_block = MagicMock(return_value={"timestamp": 1_700_000_000})

    csa = MagicMock()
    for evt_name in [
        "BondDepositedETH",
        "BondDepositedStETH",
        "BondDepositedWstETH",
        "BondClaimedStETH",
        "BondClaimedUnstETH",
        "BondClaimedWstETH",
        "BondBurned",
        "BondCharged",
    ]:
        evt_obj = MagicMock()
        evt_obj.get_logs = get_logs_by_event.get(evt_name, lambda **kw: [])
        setattr(csa.events, evt_name, evt_obj)
    provider.csaccounting = csa
    return provider


def _make_log(block_number, amount_wei, *, field="amount"):
    """Build a fake event log entry shaped like web3.py returns."""
    return {
        "args": {field: amount_wei, "nodeOperatorId": 457},
        "blockNumber": block_number,
        "transactionHash": MagicMock(hex=lambda: "0xabc"),
    }


def test_get_bond_event_history_skips_pruned_chunks_doesnt_abort(monkeypatch):
    """Pruned-receipt errors from old blocks must NOT count toward the 3-strike
    abort. The scan must continue past the pruned range and collect events from
    the unpruned region.

    Reproduces the operator-457 bug: Nethermind prunes receipts before block
    ~20,974,012; scanning from CSM deployment (20,873,000) hits 3 pruned chunks
    and aborts before reaching real deposits.
    """
    get_cache().clear()

    # CSM deployment block from get_bond_event_history default
    PRUNE_CUTOFF = 20_974_000
    DEPOSIT_BLOCK = 23_819_200  # post-cutoff, where operator 457's real deposit lives
    HEAD_BLOCK = 25_161_527

    def deposited_eth_get_logs(**kwargs):
        from_blk = kwargs["from_block"]
        to_blk = kwargs["to_block"]
        if to_blk < PRUNE_CUTOFF:
            # Nethermind pruned-receipt error
            raise Exception(
                {"code": -32000, "message": f"Receipt not available for From block {from_blk}."}
            )
        if from_blk <= DEPOSIT_BLOCK <= to_blk:
            return [_make_log(DEPOSIT_BLOCK, 32 * 10**18)]
        return []

    provider = _make_bond_provider(
        block_number=HEAD_BLOCK,
        get_logs_by_event={"BondDepositedETH": deposited_eth_get_logs},
    )

    events = asyncio.run(provider.get_bond_event_history(operator_id=457))

    assert len(events) == 1, (
        f"Expected 1 event past the pruning cutoff, got {len(events)}. "
        "Before the fix, the 3-strike abort fires on the first 3 pruned chunks "
        "and the scan never reaches the deposit at block 23,819,200."
    )
    assert events[0]["event_type"] == "deposit_eth"
    assert events[0]["block_number"] == DEPOSIT_BLOCK
    assert events[0]["amount_eth"] == 32.0


def test_get_bond_event_history_still_aborts_on_real_rpc_failures(monkeypatch):
    """Non-pruning RPC errors (timeouts, connection drops) must still trip the
    3-strike abort — we don't want to mask actual broken RPCs."""
    get_cache().clear()

    def always_timeout(**kwargs):
        raise Exception("RPC timeout: eth_getLogs request timed out after 30s")

    # Range needs to span at least 3 × chunk_size (50k) to allow the 3-strike
    # abort to trigger on its third failed chunk.
    provider = _make_bond_provider(
        block_number=21_000_000,
        get_logs_by_event={"BondDepositedETH": always_timeout},
    )

    events = asyncio.run(
        provider.get_bond_event_history(operator_id=457, start_block=20_800_000)
    )

    assert events == []
    # Real RPC failures should still surface as a warning
    assert any("Bond event scan aborted" in w for w in provider._data_warnings), (
        f"Expected an 'aborted' warning for real RPC failures, got: {provider._data_warnings}"
    )


def test_get_bond_event_history_empty_result_cached_with_short_ttl(monkeypatch):
    """When the scan returns no events (likely a scan failure), the result must
    NOT be cached for the full 1-hour TTL — otherwise a poisoned empty result
    persists for an hour and refreshes can't recover.

    Empty results get a short TTL (60s) so a retry can quickly fix the state.
    """
    get_cache().clear()

    provider = _make_bond_provider(
        block_number=25_000_000,
        get_logs_by_event={},  # all events return []
    )

    asyncio.run(provider.get_bond_event_history(operator_id=999, start_block=24_990_000))

    # Probe the cache directly to check TTL
    cache = get_cache()
    # The cache key includes operator_id and start_block; find it.
    matching_entries = [
        (k, expiry) for k, (_v, expiry) in cache._cache.items()
    ]
    assert len(matching_entries) == 1, (
        f"Expected exactly one cached bond_events entry, got {len(matching_entries)}"
    )
    _key, expiry = matching_entries[0]
    from datetime import datetime, timedelta
    remaining = (expiry - datetime.now()).total_seconds()
    assert remaining < 120, (
        f"Empty bond_events result should have TTL < 120s (got {remaining:.0f}s). "
        "Caching empty results for 1h poisons subsequent fetches."
    )


def test_get_bond_event_history_non_empty_result_cached_for_full_hour():
    """Non-empty results are still cached for the full 1h TTL — the short TTL
    is only for empty results that likely indicate scan failure."""
    get_cache().clear()

    HEAD = 25_000_000
    DEPOSIT_BLOCK = 24_995_000

    def deposit_get_logs(**kwargs):
        from_blk = kwargs["from_block"]
        to_blk = kwargs["to_block"]
        if from_blk <= DEPOSIT_BLOCK <= to_blk:
            return [_make_log(DEPOSIT_BLOCK, 32 * 10**18)]
        return []

    provider = _make_bond_provider(
        block_number=HEAD,
        get_logs_by_event={"BondDepositedETH": deposit_get_logs},
    )

    events = asyncio.run(provider.get_bond_event_history(operator_id=42, start_block=24_990_000))
    assert len(events) == 1

    cache = get_cache()
    matching_entries = list(cache._cache.items())
    assert len(matching_entries) == 1
    _key, (_v, expiry) = matching_entries[0]
    from datetime import datetime
    remaining = (expiry - datetime.now()).total_seconds()
    assert remaining > 1800, (
        f"Non-empty bond_events should have TTL ~3600s (got {remaining:.0f}s)"
    )
