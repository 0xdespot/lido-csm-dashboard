"""Unit tests for operator service helper logic."""

from src.services.operator_service import allocate_claimed_shares_to_frames


def test_allocate_claimed_shares_partial_oldest_first():
    frame_shares = [100, 200, 300]
    distributed_shares = 250

    allocated = allocate_claimed_shares_to_frames(frame_shares, distributed_shares)

    assert allocated == [100, 150, 0]


def test_allocate_claimed_shares_full_claim():
    frame_shares = [10, 20, 30]
    distributed_shares = 60

    allocated = allocate_claimed_shares_to_frames(frame_shares, distributed_shares)

    assert allocated == [10, 20, 30]


def test_allocate_claimed_shares_over_claim_clamped():
    frame_shares = [10, 20]
    distributed_shares = 100

    allocated = allocate_claimed_shares_to_frames(frame_shares, distributed_shares)

    assert allocated == [10, 20]


def test_allocate_claimed_shares_zero_or_negative():
    frame_shares = [10, 20, 30]

    assert allocate_claimed_shares_to_frames(frame_shares, 0) == [0, 0, 0]
    assert allocate_claimed_shares_to_frames(frame_shares, -5) == [0, 0, 0]
