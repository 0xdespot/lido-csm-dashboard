"""Tests for IPFS distribution-log payload validation and caching."""

import json

import pytest

from src.data.ipfs_logs import (
    IPFSLogProvider,
    is_valid_log_payload,
    normalize_log_frames,
)


@pytest.fixture
def provider(tmp_path):
    return IPFSLogProvider(cache_dir=tmp_path)


VALID = {
    "frame": [434490, 440789],
    "operators": {"457": {"distributed_rewards": 123, "validators": {}}},
}


class TestIsValidLogPayload:
    def test_accepts_a_real_log_shape(self):
        assert is_valid_log_payload(VALID) is True

    def test_rejects_non_dict(self):
        assert is_valid_log_payload([1, 2, 3]) is False
        assert is_valid_log_payload("nope") is False
        assert is_valid_log_payload(None) is False

    def test_rejects_missing_frame(self):
        assert is_valid_log_payload({"operators": {}}) is False

    def test_rejects_malformed_frame(self):
        """The (0, 0) fallback this produces is what drove the hang."""
        assert is_valid_log_payload({"frame": [], "operators": {}}) is False
        assert is_valid_log_payload({"frame": [1], "operators": {}}) is False
        assert is_valid_log_payload({"frame": "434490", "operators": {}}) is False

    def test_rejects_non_numeric_frame_bounds(self):
        assert is_valid_log_payload({"frame": ["a", "b"], "operators": {}}) is False

    def test_rejects_missing_or_wrong_type_operators(self):
        assert is_valid_log_payload({"frame": [1, 2]}) is False
        assert is_valid_log_payload({"frame": [1, 2], "operators": []}) is False

    def test_accepts_extra_keys(self):
        payload = dict(VALID, blockstamp={"block_number": 1}, rebate_to_protocol=0)
        assert is_valid_log_payload(payload) is True


class TestCachePoisoning:
    def test_valid_payload_is_cached(self, provider, tmp_path):
        provider._save_to_cache("QmGood", VALID)
        assert (tmp_path / "QmGood.json").exists()
        assert provider._load_from_cache("QmGood") == VALID

    def test_malformed_payload_is_not_cached(self, provider, tmp_path):
        """A bad gateway response must not become sticky on disk."""
        provider._save_to_cache("QmBad", {"frame": "broken"})

        assert not (tmp_path / "QmBad.json").exists()
        assert provider._load_from_cache("QmBad") is None

    def test_existing_poisoned_cache_entry_is_rejected_on_read(self, provider, tmp_path):
        """Entries written before this validation existed are discarded."""
        (tmp_path / "QmPoisoned.json").write_text(json.dumps({"frame": "broken"}))

        assert provider._load_from_cache("QmPoisoned") is None
        assert not (tmp_path / "QmPoisoned.json").exists(), "poisoned entry should be removed"

    def test_corrupt_json_still_removed(self, provider, tmp_path):
        (tmp_path / "QmCorrupt.json").write_text("{not json")

        assert provider._load_from_cache("QmCorrupt") is None
        assert not (tmp_path / "QmCorrupt.json").exists()


# The distribution log format gained a versioned envelope: instead of the frame
# object sitting at the top level, it is wrapped as
# {"_ver": 1, "frames": [<frame>, ...]}. The inner frame keeps the old schema.
V1_ENVELOPE = {
    "_ver": 1,
    "frames": [
        {
            "blockstamp": {"block_number": 25875597},
            "distributable": 72837946402940483954,
            "distributed_rewards": 45816753153235799931,
            "frame": [465990, 472289],
            "operators": {"457": {"distributed_rewards": "425672527568186470", "validators": {}}},
            "rebate_to_protocol": 27021193249704684023,
        }
    ],
}


class TestVersionedEnvelope:
    def test_envelope_is_accepted_as_valid(self):
        assert is_valid_log_payload(V1_ENVELOPE) is True

    def test_envelope_normalizes_to_its_inner_frames(self):
        frames = normalize_log_frames(V1_ENVELOPE)
        assert len(frames) == 1
        assert frames[0]["frame"] == [465990, 472289]

    def test_legacy_top_level_frame_normalizes_to_one_frame(self):
        assert normalize_log_frames(VALID) == [VALID]

    def test_envelope_with_multiple_frames_keeps_all(self):
        """The list form allows more than one frame per CID; none may be dropped."""
        second = dict(V1_ENVELOPE["frames"][0], frame=[472290, 478589])
        payload = {"_ver": 1, "frames": [V1_ENVELOPE["frames"][0], second]}

        frames = normalize_log_frames(payload)

        assert [f["frame"] for f in frames] == [[465990, 472289], [472290, 478589]]

    def test_envelope_with_no_frames_is_invalid(self):
        assert is_valid_log_payload({"_ver": 1, "frames": []}) is False

    def test_envelope_with_malformed_inner_frame_is_invalid(self):
        assert is_valid_log_payload({"_ver": 1, "frames": [{"frame": "nope"}]}) is False

    def test_unknown_shape_normalizes_to_nothing(self):
        assert normalize_log_frames({"something": "else"}) == []
        assert normalize_log_frames(None) == []

    def test_envelope_is_cacheable(self, provider, tmp_path):
        provider._save_to_cache("QmEnvelope", V1_ENVELOPE)
        assert provider._load_from_cache("QmEnvelope") == V1_ENVELOPE


class TestOperatorHistoryAcrossFormats:
    @pytest.mark.asyncio
    async def test_reads_both_legacy_and_envelope_logs(self, provider, monkeypatch):
        """A mix of old and new logs must all produce frames."""
        legacy = {
            "frame": [434490, 440789],
            "operators": {"457": {"distributed_rewards": 111, "validators": {"a": {}}}},
        }
        payloads = {"QmOld": legacy, "QmNew": V1_ENVELOPE}

        async def fake_fetch(cid):
            return payloads[cid]

        monkeypatch.setattr(provider, "fetch_log", fake_fetch)

        frames, failed = await provider.get_operator_history(
            457, [{"logCid": "QmOld", "block": 1}, {"logCid": "QmNew", "block": 2}]
        )

        assert failed == 0
        assert [f.start_epoch for f in frames] == [434490, 465990]
        assert frames[0].distributed_rewards == 111
        assert frames[1].distributed_rewards == 425672527568186470

    @pytest.mark.asyncio
    async def test_multi_frame_envelope_yields_every_frame(self, provider, monkeypatch):
        second = dict(
            V1_ENVELOPE["frames"][0],
            frame=[472290, 478589],
            operators={"457": {"distributed_rewards": "999", "validators": {}}},
        )

        async def fake_fetch(cid):
            return {"_ver": 1, "frames": [V1_ENVELOPE["frames"][0], second]}

        monkeypatch.setattr(provider, "fetch_log", fake_fetch)

        frames, failed = await provider.get_operator_history(
            457, [{"logCid": "QmMulti", "block": 1}]
        )

        assert failed == 0
        assert [f.start_epoch for f in frames] == [465990, 472290]


class TestRewardsCoercion:
    """The versioned format quotes wei amounts as strings; the legacy one did not."""

    def test_string_rewards_coerced_to_int(self, provider):
        frame = {"frame": [1, 2], "operators": {"457": {"distributed_rewards": "425672527568186470"}}}
        assert provider.get_operator_frame_rewards(frame, 457) == 425672527568186470

    def test_int_rewards_pass_through(self, provider):
        frame = {"frame": [1, 2], "operators": {"457": {"distributed_rewards": 123}}}
        assert provider.get_operator_frame_rewards(frame, 457) == 123

    def test_legacy_distributed_key_still_read(self, provider):
        frame = {"frame": [1, 2], "operators": {"457": {"distributed": "456"}}}
        assert provider.get_operator_frame_rewards(frame, 457) == 456

    def test_operator_absent_returns_none(self, provider):
        frame = {"frame": [1, 2], "operators": {"999": {"distributed_rewards": 1}}}
        assert provider.get_operator_frame_rewards(frame, 457) is None

    def test_unparseable_rewards_do_not_raise(self, provider):
        frame = {"frame": [1, 2], "operators": {"457": {"distributed_rewards": "not-a-number"}}}
        assert provider.get_operator_frame_rewards(frame, 457) == 0

    def test_summing_mixed_format_frames_works(self, provider):
        """The regression: str + int in a sum() used to raise and blank the history."""
        legacy = {"frame": [1, 2], "operators": {"457": {"distributed_rewards": 100}}}
        modern = {"frame": [3, 4], "operators": {"457": {"distributed_rewards": "200"}}}
        total = sum(provider.get_operator_frame_rewards(f, 457) for f in (legacy, modern))
        assert total == 300
