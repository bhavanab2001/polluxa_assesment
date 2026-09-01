"""Tests for Data Quality checks and composite scoring."""

from src.quality.scoring import DIMENSION_WEIGHTS


def test_dimension_weights_sum_to_one():
    total_weight = sum(DIMENSION_WEIGHTS.values())
    assert abs(total_weight - 1.0) < 1e-6
    assert "completeness" in DIMENSION_WEIGHTS
    assert "uniqueness" in DIMENSION_WEIGHTS
    assert "validity" in DIMENSION_WEIGHTS
    assert "timeliness" in DIMENSION_WEIGHTS
    assert "referential_integrity" in DIMENSION_WEIGHTS
