"""
Anomaly detection for LinkedIn outreach metrics.

Uses a hybrid Z-Score + IQR approach to detect:
- Acceptance-rate collapse
- Reply decay
- Ghosting patterns
- Unusual activity spikes

Statistical basis:
- Z-Score: Detects gradual drift from a 14-day rolling baseline.
  Assumes approximately normal distribution within stable operating periods.
- IQR: Detects sudden outliers without normality assumption.
  Robust to non-normal distributions and small sample sizes.

Scoring:
- 0 = Normal
- 1 = Warning (Z > 2.0 or outside 1.5×IQR)
- 2 = Critical (Z > 3.0 or outside 3.0×IQR)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from src.logging_config import get_logger

logger = get_logger("anomaly")


@dataclass
class AnomalyResult:
    """Result of anomaly detection for a single metric."""

    metric_name: str
    current_value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    iqr_lower: float
    iqr_upper: float
    anomaly_score: int  # 0=normal, 1=warning, 2=critical
    method_triggered: str  # "none", "z_score", "iqr", "both"
    details: dict = field(default_factory=dict)


class AnomalyDetector:
    """
    Hybrid Z-Score + IQR anomaly detector.

    Computes anomaly scores for outreach metrics against a
    rolling baseline window. Designed for per-agent, per-day analysis.
    """

    # Thresholds
    Z_WARNING = 2.0
    Z_CRITICAL = 3.0
    IQR_WARNING_MULTIPLIER = 1.5
    IQR_CRITICAL_MULTIPLIER = 3.0
    MIN_BASELINE_POINTS = 5  # Minimum data points for meaningful detection

    def __init__(self, baseline_window: int = 14):
        """
        Args:
            baseline_window: Number of days to use for the rolling baseline.
        """
        self.baseline_window = baseline_window

    def detect(
        self,
        values: list[float] | NDArray,
        metric_name: str = "metric",
    ) -> AnomalyResult:
        """
        Detect anomalies in the latest value against the baseline.

        Args:
            values: Time series of metric values (oldest first, latest last).
                    Must have at least MIN_BASELINE_POINTS + 1 elements.
            metric_name: Human-readable name for logging.

        Returns:
            AnomalyResult with anomaly score and details.
        """
        arr = np.array(values, dtype=float)

        if len(arr) < self.MIN_BASELINE_POINTS + 1:
            return AnomalyResult(
                metric_name=metric_name,
                current_value=arr[-1] if len(arr) > 0 else 0.0,
                baseline_mean=0.0,
                baseline_std=0.0,
                z_score=0.0,
                iqr_lower=0.0,
                iqr_upper=0.0,
                anomaly_score=0,
                method_triggered="none",
                details={"reason": "insufficient_baseline_data", "data_points": len(arr)},
            )

        current = arr[-1]
        baseline = arr[-self.baseline_window - 1 : -1]  # Exclude the latest point

        if len(baseline) < self.MIN_BASELINE_POINTS:
            baseline = arr[:-1]

        # ── Z-Score ──────────────────────────────────────────
        mean = np.mean(baseline)
        std = np.std(baseline, ddof=1)  # Sample std for small datasets

        if std > 0:
            z_score = abs((current - mean) / std)
        else:
            z_score = 0.0  # All baseline values identical

        # ── IQR ──────────────────────────────────────────────
        q1 = np.percentile(baseline, 25)
        q3 = np.percentile(baseline, 75)
        iqr = q3 - q1

        iqr_lower_warning = q1 - self.IQR_WARNING_MULTIPLIER * iqr
        iqr_upper_warning = q3 + self.IQR_WARNING_MULTIPLIER * iqr
        iqr_lower_critical = q1 - self.IQR_CRITICAL_MULTIPLIER * iqr
        iqr_upper_critical = q3 + self.IQR_CRITICAL_MULTIPLIER * iqr

        # ── Scoring ──────────────────────────────────────────
        z_flag = 0
        if z_score >= self.Z_CRITICAL:
            z_flag = 2
        elif z_score >= self.Z_WARNING:
            z_flag = 1

        iqr_flag = 0
        if current < iqr_lower_critical or current > iqr_upper_critical:
            iqr_flag = 2
        elif current < iqr_lower_warning or current > iqr_upper_warning:
            iqr_flag = 1

        # Combined: take the maximum signal
        anomaly_score = max(z_flag, iqr_flag)

        if z_flag > 0 and iqr_flag > 0:
            method = "both"
        elif z_flag > 0:
            method = "z_score"
        elif iqr_flag > 0:
            method = "iqr"
        else:
            method = "none"

        result = AnomalyResult(
            metric_name=metric_name,
            current_value=float(current),
            baseline_mean=float(mean),
            baseline_std=float(std),
            z_score=float(z_score),
            iqr_lower=float(iqr_lower_warning),
            iqr_upper=float(iqr_upper_warning),
            anomaly_score=anomaly_score,
            method_triggered=method,
            details={
                "baseline_points": len(baseline),
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(iqr),
                "z_flag": z_flag,
                "iqr_flag": iqr_flag,
            },
        )

        if anomaly_score > 0:
            logger.warning(
                "anomaly_detected",
                metric=metric_name,
                score=anomaly_score,
                current=round(current, 4),
                mean=round(mean, 4),
                z_score=round(z_score, 2),
                method=method,
            )

        return result

    def detect_rate_collapse(
        self,
        rates: list[float],
        metric_name: str = "rate",
    ) -> AnomalyResult:
        """
        Specifically detect rate collapse — a sudden drop in acceptance
        or reply rates. Uses one-sided detection (only flags drops).
        """
        arr = np.array(rates, dtype=float)

        if len(arr) < self.MIN_BASELINE_POINTS + 1:
            return AnomalyResult(
                metric_name=metric_name,
                current_value=arr[-1] if len(arr) > 0 else 0.0,
                baseline_mean=0.0,
                baseline_std=0.0,
                z_score=0.0,
                iqr_lower=0.0,
                iqr_upper=0.0,
                anomaly_score=0,
                method_triggered="none",
                details={"reason": "insufficient_data"},
            )

        current = arr[-1]
        baseline = arr[-self.baseline_window - 1 : -1]
        if len(baseline) < self.MIN_BASELINE_POINTS:
            baseline = arr[:-1]

        mean = np.mean(baseline)
        std = np.std(baseline, ddof=1)

        # One-sided: only flag if current is BELOW baseline
        if std > 0 and current < mean:
            z_score = (mean - current) / std
        else:
            z_score = 0.0

        anomaly_score = 0
        if z_score >= self.Z_CRITICAL:
            anomaly_score = 2
        elif z_score >= self.Z_WARNING:
            anomaly_score = 1

        return AnomalyResult(
            metric_name=metric_name,
            current_value=float(current),
            baseline_mean=float(mean),
            baseline_std=float(std),
            z_score=float(z_score),
            iqr_lower=float(np.percentile(baseline, 25)),
            iqr_upper=float(np.percentile(baseline, 75)),
            anomaly_score=anomaly_score,
            method_triggered="z_score_one_sided" if anomaly_score > 0 else "none",
            details={"direction": "drop", "baseline_points": len(baseline)},
        )

    def detect_ghosting(
        self,
        accepted_counts: list[int],
        reply_counts: list[int],
        window_days: int = 7,
    ) -> AnomalyResult:
        """
        Detect ghosting pattern — accepted connections that never replied
        within a window period.

        Ghost rate = (accepted - replied) / accepted
        """
        if not accepted_counts or not reply_counts:
            return AnomalyResult(
                metric_name="ghosting_rate",
                current_value=0.0,
                baseline_mean=0.0,
                baseline_std=0.0,
                z_score=0.0,
                iqr_lower=0.0,
                iqr_upper=0.0,
                anomaly_score=0,
                method_triggered="none",
                details={"reason": "no_data"},
            )

        # Compute ghost rates for each period
        ghost_rates: list[float] = []
        for acc, rep in zip(accepted_counts, reply_counts):
            if acc > 0:
                ghost_rates.append((acc - min(rep, acc)) / acc)
            else:
                ghost_rates.append(0.0)

        return self.detect(ghost_rates, metric_name="ghosting_rate")
