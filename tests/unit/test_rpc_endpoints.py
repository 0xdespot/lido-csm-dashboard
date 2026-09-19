"""Tests for multi-endpoint RPC selection and failover."""

import pytest

from src.core.rpc_errors import RPCUnavailableError
from src.data import rpc_endpoints
from src.data.rpc_endpoints import (
    invalidate_rpc_selection,
    parse_rpc_candidates,
    select_rpc_url,
)


@pytest.fixture(autouse=True)
def _clean_selection():
    """Each test starts with no memoized endpoint."""
    invalidate_rpc_selection()
    yield
    invalidate_rpc_selection()


class TestParseRpcCandidates:
    def test_single_url(self):
        assert parse_rpc_candidates("https://a.example") == ["https://a.example"]

    def test_comma_separated_list_is_split_and_stripped(self):
        raw = "http://192.168.1.50:8545, https://a.example ,https://b.example"
        assert parse_rpc_candidates(raw) == [
            "http://192.168.1.50:8545",
            "https://a.example",
            "https://b.example",
        ]

    def test_blank_entries_and_trailing_commas_dropped(self):
        assert parse_rpc_candidates("https://a.example,,  ,") == ["https://a.example"]

    def test_empty_string_yields_no_candidates(self):
        assert parse_rpc_candidates("   ") == []

    def test_order_is_preserved(self):
        raw = "https://c.example,https://a.example,https://b.example"
        assert parse_rpc_candidates(raw)[0] == "https://c.example"


class TestSelectRpcUrl:
    def test_single_candidate_is_returned_without_probing(self):
        """The common single-endpoint config must not pay for a probe."""
        calls = []

        def probe(url):
            calls.append(url)
            return 1

        assert select_rpc_url(["https://a.example"], probe=probe) == "https://a.example"
        assert calls == []

    def test_first_responsive_candidate_wins(self):
        def probe(url):
            return 1

        urls = ["https://a.example", "https://b.example"]
        assert select_rpc_url(urls, probe=probe) == "https://a.example"

    def test_falls_through_to_second_when_first_fails(self):
        tried = []

        def probe(url):
            tried.append(url)
            if url == "https://dead.example":
                raise ConnectionError("refused")
            return 1

        urls = ["https://dead.example", "https://live.example"]
        assert select_rpc_url(urls, probe=probe) == "https://live.example"
        assert tried == urls

    def test_skips_multiple_dead_endpoints(self):
        def probe(url):
            if "live" not in url:
                raise ConnectionError("refused")
            return 1

        urls = ["http://d1.example", "http://d2.example", "https://live.example"]
        assert select_rpc_url(urls, probe=probe) == "https://live.example"

    def test_raises_only_when_every_candidate_fails(self):
        def probe(url):
            raise ConnectionError("refused")

        with pytest.raises(RPCUnavailableError) as exc:
            select_rpc_url(["http://d1.example:8545", "https://d2.example"], probe=probe)

        # Names every host tried, so the UI message is actionable.
        assert "d1.example" in exc.value.host
        assert "d2.example" in exc.value.host

    def test_no_candidates_raises(self):
        with pytest.raises(RPCUnavailableError):
            select_rpc_url([], probe=lambda url: 1)

    def test_error_never_leaks_credentials_in_url(self):
        """A key embedded in the path must not reach the error message."""
        def probe(url):
            raise ConnectionError("refused")

        with pytest.raises(RPCUnavailableError) as exc:
            select_rpc_url(
                ["https://rpc.example/v3/SUPERSECRETKEY", "https://b.example/AnotherSecret"],
                probe=probe,
            )

        assert "SUPERSECRETKEY" not in str(exc.value)
        assert "AnotherSecret" not in str(exc.value)
        assert "rpc.example" in exc.value.host


class TestSelectionMemo:
    def test_selection_is_memoized(self):
        calls = []

        def probe(url):
            calls.append(url)
            return 1

        urls = ["https://a.example", "https://b.example"]
        select_rpc_url(urls, probe=probe)
        select_rpc_url(urls, probe=probe)
        select_rpc_url(urls, probe=probe)

        assert len(calls) == 1, "memoized selection should probe once"

    def test_invalidate_forces_a_reprobe(self):
        calls = []

        def probe(url):
            calls.append(url)
            return 1

        urls = ["https://a.example", "https://b.example"]
        select_rpc_url(urls, probe=probe)
        invalidate_rpc_selection()
        select_rpc_url(urls, probe=probe)

        assert len(calls) == 2

    def test_reprobe_after_invalidate_fails_over(self):
        """The real failover path: primary dies mid-session, next call moves on."""
        state = {"primary_up": True}

        def probe(url):
            if url == "https://primary.example":
                if not state["primary_up"]:
                    raise ConnectionError("refused")
                return 1
            return 1

        urls = ["https://primary.example", "https://backup.example"]
        assert select_rpc_url(urls, probe=probe) == "https://primary.example"

        state["primary_up"] = False
        invalidate_rpc_selection()
        assert select_rpc_url(urls, probe=probe) == "https://backup.example"

    def test_memo_expires_after_ttl(self, monkeypatch):
        calls = []

        def probe(url):
            calls.append(url)
            return 1

        clock = {"t": 1000.0}
        monkeypatch.setattr(rpc_endpoints.time, "monotonic", lambda: clock["t"])

        urls = ["https://a.example", "https://b.example"]
        select_rpc_url(urls, probe=probe)
        clock["t"] += rpc_endpoints.RPC_SELECTION_TTL + 1
        select_rpc_url(urls, probe=probe)

        assert len(calls) == 2

    def test_memo_ignored_when_candidate_list_changes(self):
        """A memoized URL that is no longer configured must not be reused."""
        def probe(url):
            return 1

        select_rpc_url(["https://a.example", "https://b.example"], probe=probe)
        assert select_rpc_url(["https://c.example", "https://d.example"], probe=probe) == "https://c.example"
