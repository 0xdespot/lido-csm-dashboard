"""Tests for the next-distribution date estimate.

A malformed IPFS log yields a zero-length frame, which previously drove an
unbounded `while` loop — spinning a worker thread at 100% CPU forever, with no
request timeout anywhere to stop it.
"""

from datetime import datetime, timedelta, timezone

from src.data.ipfs_logs import epoch_to_datetime
from src.services.operator_service import estimate_next_distribution_date

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)


def _epoch_at(dt: datetime) -> int:
    """Smallest epoch whose timestamp is >= dt."""
    lo, hi = 0, 10_000_000
    while lo < hi:
        mid = (lo + hi) // 2
        if epoch_to_datetime(mid) < dt:
            lo = mid + 1
        else:
            hi = mid
    return lo


class TestEstimateNextDistributionDate:
    def test_returns_none_for_zero_length_frame(self):
        """get_frame_info returns (0, 0) for a malformed log — must not hang."""
        assert estimate_next_distribution_date(0, 0, NOW) is None

    def test_returns_none_for_equal_epochs(self):
        epoch = _epoch_at(NOW - timedelta(days=30))
        assert estimate_next_distribution_date(epoch, epoch, NOW) is None

    def test_returns_none_for_negative_duration(self):
        """Reversed epochs would step backwards forever."""
        end = _epoch_at(NOW - timedelta(days=60))
        start = _epoch_at(NOW - timedelta(days=30))
        assert estimate_next_distribution_date(start, end, NOW) is None

    def test_zero_length_frame_terminates_promptly(self):
        """Regression guard: this call used to never return."""
        started = datetime.now(timezone.utc)
        assert estimate_next_distribution_date(0, 0, NOW) is None
        assert (datetime.now(timezone.utc) - started).total_seconds() < 1

    def test_advances_past_now_for_a_stale_frame(self):
        """IPFS logs lagging months behind still produce a future date."""
        start = _epoch_at(NOW - timedelta(days=90))
        end = _epoch_at(NOW - timedelta(days=62))

        result = estimate_next_distribution_date(start, end, NOW)

        assert result is not None
        assert datetime.fromisoformat(result) >= NOW

    def test_next_frame_when_current_frame_is_recent(self):
        """A frame that just ended projects one duration forward, not further."""
        start = _epoch_at(NOW - timedelta(days=28))
        end = _epoch_at(NOW - timedelta(days=1))

        result = estimate_next_distribution_date(start, end, NOW)

        assert result is not None
        projected = datetime.fromisoformat(result)
        assert projected >= NOW
        assert projected <= NOW + timedelta(days=28)
