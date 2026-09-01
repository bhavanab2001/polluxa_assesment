"""Tests for statistical anomaly detection and risk modeling."""

import numpy as np
import pytest
from src.analytics.anomaly import AnomalyDetector


def test_anomaly_detection_normal():
    detector = AnomalyDetector(baseline_window=14)
    baseline = [10.0, 10.2, 9.8, 10.1, 10.0, 9.9, 10.1, 10.0, 10.2, 9.8, 10.0, 10.1, 10.0, 10.0]
    result = detector.detect(baseline + [10.1], metric_name="test_volume")
    assert result.anomaly_score == 0
    assert result.method_triggered == "none"


def test_anomaly_detection_spike():
    detector = AnomalyDetector(baseline_window=14)
    baseline = [10.0, 10.2, 9.8, 10.1, 10.0, 9.9, 10.1, 10.0, 10.2, 9.8, 10.0, 10.1, 10.0, 10.0]
    result = detector.detect(baseline + [35.0], metric_name="test_spike")
    assert result.anomaly_score >= 1


def test_rate_collapse_detection():
    detector = AnomalyDetector(baseline_window=14)
    baseline = [0.35, 0.38, 0.34, 0.36, 0.35, 0.37, 0.35, 0.36, 0.34, 0.35, 0.36, 0.35, 0.37, 0.35]
    # Collapse to 0.05
    result = detector.detect_rate_collapse(baseline + [0.05], metric_name="acceptance_rate")
    assert result.anomaly_score >= 1
    assert result.details["direction"] == "drop"
