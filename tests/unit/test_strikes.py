"""Tests for the strikes module."""

import pytest

from src.data.strikes import (
    DEFAULT_STRIKE_THRESHOLD,
    STRIKE_THRESHOLDS,
    StrikesProvider,
    ValidatorStrikes,
    get_strike_threshold,
    is_valid_validator_pubkey,
)


class TestStrikeThresholds:
    """Tests for strike threshold logic."""

    def test_strike_thresholds_mapping(self):
        """Test the STRIKE_THRESHOLDS mapping is correct."""
        assert STRIKE_THRESHOLDS[0] == 3  # Permissionless (Legacy)
        assert STRIKE_THRESHOLDS[1] == 4  # ICS/Legacy EA
        assert STRIKE_THRESHOLDS[2] == 3  # Permissionless (current)

    def test_default_strike_threshold(self):
        """Test the default strike threshold is 3."""
        assert DEFAULT_STRIKE_THRESHOLD == 3

    def test_get_strike_threshold_permissionless_legacy(self):
        """Test threshold for curve 0 (Permissionless Legacy)."""
        assert get_strike_threshold(0) == 3

    def test_get_strike_threshold_ics(self):
        """Test threshold for curve 1 (ICS/Legacy EA)."""
        assert get_strike_threshold(1) == 4

    def test_get_strike_threshold_permissionless(self):
        """Test threshold for curve 2 (Permissionless)."""
        assert get_strike_threshold(2) == 3

    def test_get_strike_threshold_unknown_curve(self):
        """Test threshold for unknown curve_id defaults to 3."""
        assert get_strike_threshold(99) == 3
        assert get_strike_threshold(100) == 3
        assert get_strike_threshold(-1) == 3


class TestValidatorStrikes:
    """Tests for ValidatorStrikes dataclass."""

    def test_validator_strikes_creation(self):
        """Test creating a ValidatorStrikes instance."""
        vs = ValidatorStrikes(
            pubkey="0x12345...",
            strikes=[1, 0, 1, 0, 0, 1],
            strike_count=3,
            strike_threshold=3,
            at_ejection_risk=True,
        )

        assert vs.pubkey == "0x12345..."
        assert vs.strike_count == 3
        assert vs.strike_threshold == 3
        assert vs.at_ejection_risk is True

    def test_validator_strikes_not_at_risk(self):
        """Test validator with 2 strikes (not at risk for permissionless)."""
        vs = ValidatorStrikes(
            pubkey="0xabc...",
            strikes=[1, 0, 1, 0, 0, 0],
            strike_count=2,
            strike_threshold=3,
            at_ejection_risk=False,
        )

        assert vs.strike_count == 2
        assert vs.at_ejection_risk is False

    def test_validator_strikes_ics_not_at_risk(self):
        """Test ICS validator with 3 strikes (not at risk since threshold is 4)."""
        vs = ValidatorStrikes(
            pubkey="0xdef...",
            strikes=[1, 1, 1, 0, 0, 0],
            strike_count=3,
            strike_threshold=4,  # ICS threshold
            at_ejection_risk=False,
        )

        assert vs.strike_count == 3
        assert vs.strike_threshold == 4
        assert vs.at_ejection_risk is False  # Not at risk because threshold is 4

    def test_validator_strikes_ics_at_risk(self):
        """Test ICS validator with 4 strikes (at risk)."""
        vs = ValidatorStrikes(
            pubkey="0xghi...",
            strikes=[1, 1, 1, 1, 0, 0],
            strike_count=4,
            strike_threshold=4,  # ICS threshold
            at_ejection_risk=True,
        )

        assert vs.strike_count == 4
        assert vs.at_ejection_risk is True

    def test_validator_strikes_empty_array(self):
        """Test validator with no strikes."""
        vs = ValidatorStrikes(
            pubkey="0xjkl...",
            strikes=[0, 0, 0, 0, 0, 0],
            strike_count=0,
            strike_threshold=3,
            at_ejection_risk=False,
        )

        assert vs.strike_count == 0
        assert vs.at_ejection_risk is False
        assert sum(vs.strikes) == 0


class TestPubkeyValidation:
    """Tests for pubkey validation and filtering."""

    def test_valid_pubkey_format(self):
        """Validator pubkeys must be 48-byte hex with 0x prefix."""
        valid_pubkey = "0x" + "ab" * 48
        assert is_valid_validator_pubkey(valid_pubkey) is True

    @pytest.mark.parametrize(
        "pubkey",
        [
            "",
            "0x1234",
            "ab" * 48,
            "0x" + "zz" * 48,
            "0x" + "ab" * 47,
            "0x" + "ab" * 49,
        ],
    )
    def test_invalid_pubkey_formats(self, pubkey):
        """Invalid pubkey formats are rejected."""
        assert is_valid_validator_pubkey(pubkey) is False

    @pytest.mark.asyncio
    async def test_get_operator_strikes_skips_invalid_pubkeys(self, tmp_path, monkeypatch):
        """Only valid validator pubkeys should be returned to API consumers."""
        provider = StrikesProvider(cache_dir=tmp_path)
        valid_pubkey = "0x" + "ab" * 48

        async def fake_tree():
            return {
                "values": [
                    {"value": [42, valid_pubkey, [1, 0, 1, 0, 0, 0]]},
                    {"value": [42, "not-a-pubkey", [1, 1, 1, 0, 0, 0]]},
                    {"value": [7, valid_pubkey, [1, 1, 1, 1, 0, 0]]},
                ]
            }

        monkeypatch.setattr(provider, "fetch_strikes_tree", fake_tree)

        strikes = await provider.get_operator_strikes(operator_id=42, curve_id=2)

        assert len(strikes) == 1
        assert strikes[0].pubkey == valid_pubkey
        assert strikes[0].strike_count == 2
