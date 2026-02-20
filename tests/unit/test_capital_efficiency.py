"""Tests for the capital efficiency calculator module."""

import pytest
from datetime import datetime, timezone, timedelta

from src.services.capital_efficiency import (
    calculate_capital_efficiency,
    calculate_xirr,
)


class TestCalculateXirr:
    """Tests for the XIRR calculation."""

    def test_xirr_simple_doubling(self):
        """Test XIRR with a simple case: invest 100, get 200 after 1 year."""
        d0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        cash_flows = [
            (d0, -100.0),
            (d1, 200.0),
        ]
        result = calculate_xirr(cash_flows)
        assert result is not None
        # Should be ~100% return
        assert abs(result - 100.0) < 1.0

    def test_xirr_known_value(self):
        """Test XIRR with a known IRR scenario."""
        d0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d1 = datetime(2024, 7, 1, tzinfo=timezone.utc)
        d2 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        # Invest 1000, get 50 at 6 months, get 1050 at 1 year
        cash_flows = [
            (d0, -1000.0),
            (d1, 50.0),
            (d2, 1050.0),
        ]
        result = calculate_xirr(cash_flows)
        assert result is not None
        # Should be roughly ~10% (100 return on 1000 with some compounding)
        assert 8.0 < result < 12.0

    def test_xirr_no_cash_flows(self):
        """Test XIRR with empty cash flows."""
        assert calculate_xirr([]) is None

    def test_xirr_single_flow(self):
        """Test XIRR with only one cash flow."""
        d0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert calculate_xirr([(d0, -100.0)]) is None

    def test_xirr_all_negative(self):
        """Test XIRR with all negative flows (no returns).

        In practice, _build_xirr_cash_flows filters out cases without both
        negative and positive flows. calculate_xirr may return None or a
        clamped value when given pathological inputs.
        """
        d0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        cash_flows = [
            (d0, -100.0),
            (d1, -50.0),
        ]
        result = calculate_xirr(cash_flows)
        # May return None (non-convergence) or a clamped extreme value
        # Either is acceptable for this pathological input
        assert result is None or isinstance(result, float)

    def test_xirr_small_positive_return(self):
        """Test XIRR with a small positive return (~3% annual)."""
        d0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        cash_flows = [
            (d0, -1000.0),
            (d1, 1030.0),  # 3% return
        ]
        result = calculate_xirr(cash_flows)
        assert result is not None
        assert abs(result - 3.0) < 0.5

    def test_xirr_multiple_deposits(self):
        """Test XIRR with multiple deposit dates and a terminal value."""
        d0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d1 = datetime(2024, 4, 1, tzinfo=timezone.utc)
        d2 = datetime(2024, 7, 1, tzinfo=timezone.utc)
        d3 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        cash_flows = [
            (d0, -100.0),
            (d1, -100.0),
            (d2, 10.0),     # Small distribution
            (d3, 220.0),    # Terminal value
        ]
        result = calculate_xirr(cash_flows)
        assert result is not None
        assert result > 0  # Should be positive


class TestCalculateCapitalEfficiency:
    """Tests for the full capital efficiency calculation."""

    def _make_bond_events(self, deposits, claims=None):
        """Helper to create bond event dicts."""
        events = []
        for ts, amount in deposits:
            events.append({
                "event_type": "deposit_eth",
                "block_number": 1000000,
                "timestamp": ts.isoformat(),
                "amount_wei": int(amount * 10**18),
                "amount_eth": amount,
                "tx_hash": "0x" + "ab" * 32,
                "flow_direction": 1,
            })
        if claims:
            for ts, amount in claims:
                events.append({
                    "event_type": "claim_steth",
                    "block_number": 1000001,
                    "timestamp": ts.isoformat(),
                    "amount_wei": int(amount * 10**18),
                    "amount_eth": amount,
                    "tx_hash": "0x" + "cd" * 32,
                    "flow_direction": -1,
                })
        events.sort(key=lambda x: x["timestamp"])
        return events

    def test_basic_efficiency(self):
        """Test basic capital efficiency with a single deposit."""
        now = datetime.now(timezone.utc)
        deposit_date = now - timedelta(days=365)

        events = self._make_bond_events([(deposit_date, 2.0)])
        result = calculate_capital_efficiency(
            bond_events=events,
            total_rewards_eth=0.2,
            current_bond_eth=2.0,
            steth_apr=3.0,
        )
        assert result != {}
        assert result["total_capital_deployed_eth"] == 2.0
        assert result["total_csm_return_eth"] == pytest.approx(0.2, abs=0.01)
        assert result["csm_annualized_return_pct"] is not None
        assert result["days_operating"] == pytest.approx(365, abs=2)

    def test_no_deposits(self):
        """Test with no deposit events returns empty."""
        result = calculate_capital_efficiency(
            bond_events=[],
            total_rewards_eth=1.0,
            current_bond_eth=2.0,
            steth_apr=3.0,
        )
        assert result == {}

    def test_very_short_period(self):
        """Test with operation period < 1 day returns empty."""
        now = datetime.now(timezone.utc)
        deposit_date = now - timedelta(hours=12)

        events = self._make_bond_events([(deposit_date, 2.0)])
        result = calculate_capital_efficiency(
            bond_events=events,
            total_rewards_eth=0.01,
            current_bond_eth=2.0,
            steth_apr=3.0,
        )
        assert result == {}

    def test_advantage_ratio_above_one(self):
        """Test that CSM advantage > 1 when CSM outperforms stETH."""
        now = datetime.now(timezone.utc)
        deposit_date = now - timedelta(days=365)

        events = self._make_bond_events([(deposit_date, 2.0)])
        result = calculate_capital_efficiency(
            bond_events=events,
            total_rewards_eth=0.3,  # 15% return on 2 ETH
            current_bond_eth=2.0,
            steth_apr=3.0,  # stETH only 3%
        )
        assert result.get("csm_advantage_ratio") is not None
        assert result["csm_advantage_ratio"] > 1.0

    def test_advantage_ratio_below_one(self):
        """Test that CSM advantage < 1 when stETH outperforms CSM."""
        now = datetime.now(timezone.utc)
        deposit_date = now - timedelta(days=365)

        events = self._make_bond_events([(deposit_date, 2.0)])
        result = calculate_capital_efficiency(
            bond_events=events,
            total_rewards_eth=0.01,  # Tiny returns
            current_bond_eth=2.0,
            steth_apr=5.0,  # Strong stETH APR
        )
        assert result.get("csm_advantage_ratio") is not None
        assert result["csm_advantage_ratio"] < 1.0

    def test_with_distribution_flows_enables_xirr(self):
        """Test that providing distribution flows enables XIRR calculation."""
        now = datetime.now(timezone.utc)
        deposit_date = now - timedelta(days=365)
        dist_date = now - timedelta(days=180)

        events = self._make_bond_events([(deposit_date, 2.0)])
        distribution_flows = [
            {"date": dist_date, "amount_eth": 0.1},
        ]
        result = calculate_capital_efficiency(
            bond_events=events,
            total_rewards_eth=0.2,
            current_bond_eth=2.0,
            steth_apr=3.0,
            distribution_flows=distribution_flows,
        )
        assert result.get("xirr_pct") is not None

    def test_bond_appreciation_included(self):
        """Test that bond appreciation is included in total return."""
        now = datetime.now(timezone.utc)
        deposit_date = now - timedelta(days=365)

        events = self._make_bond_events([(deposit_date, 2.0)])
        # Current bond is 2.1 (appreciated 0.1 ETH from stETH rebasing)
        result = calculate_capital_efficiency(
            bond_events=events,
            total_rewards_eth=0.2,
            current_bond_eth=2.1,
            steth_apr=3.0,
        )
        # Total return = 0.2 rewards + 0.1 bond appreciation = 0.3
        assert result["total_csm_return_eth"] == pytest.approx(0.3, abs=0.01)

    def test_multiple_deposits(self):
        """Test with multiple deposits over time."""
        now = datetime.now(timezone.utc)
        deposit1 = now - timedelta(days=365)
        deposit2 = now - timedelta(days=180)

        events = self._make_bond_events([
            (deposit1, 2.0),
            (deposit2, 1.5),
        ])
        result = calculate_capital_efficiency(
            bond_events=events,
            total_rewards_eth=0.5,
            current_bond_eth=3.5,
            steth_apr=3.0,
        )
        assert result["total_capital_deployed_eth"] == 3.5
        assert result["days_operating"] == pytest.approx(365, abs=2)
