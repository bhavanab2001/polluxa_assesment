# Risk Model — Statistical Methodology

## Overview

The Polluxa Risk Model detects hidden operational risks in LinkedIn outreach agents and recommends optimized daily capacity limits. It uses a **hybrid Z-Score + IQR approach** applied to rolling 14-day baselines.

## Method Selection Justification

### Why Z-Score + IQR?

| Method | Strengths | Weaknesses | Fit for Our Data |
|--------|-----------|------------|------------------|
| **Z-Score** | Detects gradual drift from baseline; interpretable threshold (σ units) | Assumes approximate normality; sensitive to outliers in baseline | ✅ LinkedIn outreach rates are approximately normal within stable periods |
| **IQR** | Distribution-free; robust to outliers; works with small samples | Less sensitive to gradual trends | ✅ Catches sudden single-day spikes/drops |
| Isolation Forest | Good for high-dimensional data | Overkill for 4-5 metrics; less interpretable | ❌ Over-engineered for this use case |
| ARIMA/Prophet | Models temporal patterns | Requires much more data (months); complex tuning | ❌ Insufficient data for time-series decomposition |

**Decision:** The hybrid approach gives us the best of both worlds — Z-Score catches gradual rate decay while IQR catches sudden outliers — with full interpretability and minimal data requirements.

## Metrics Scored

| Metric | Source | Detection Mode | Why It Matters |
|--------|--------|----------------|----------------|
| **Acceptance Rate** | `fact_daily_agent_activity.acceptance_rate` | One-sided (drops only) | Collapse signals potential shadow-ban or targeting issues |
| **Reply Rate** | `fact_daily_agent_activity.reply_rate` | One-sided (drops only) | Decay indicates message quality degradation or audience exhaustion |
| **Ghosting Rate** | Computed: `(accepted - replied) / accepted` | Two-sided | High ghosting means connections are unresponsive |
| **Utilisation %** | `fact_daily_agent_activity.utilisation_pct` | Two-sided | Over-utilisation risks rate limits; under-utilisation wastes capacity |
| **Activity Volume** | `fact_daily_agent_activity.invites_sent` | Two-sided | Sudden spikes or drops in volume are suspicious |

## Anomaly Scoring Algorithm

### Step 1: Compute Baseline Statistics
For the current day's value, use the preceding 14 days as the baseline:

```
baseline = values[t-14 : t-1]
μ = mean(baseline)
σ = std(baseline, ddof=1)  # Sample standard deviation
Q1, Q3 = percentile(baseline, [25, 75])
IQR = Q3 - Q1
```

### Step 2: Z-Score Detection
```
z = |current_value - μ| / σ

if z ≥ 3.0  →  z_flag = 2 (Critical)
elif z ≥ 2.0  →  z_flag = 1 (Warning)
else  →  z_flag = 0 (Normal)
```

For rate collapse metrics (acceptance, reply), use one-sided detection:
```
z = (μ - current_value) / σ   # Only flag drops
```

### Step 3: IQR Detection
```
if value < Q1 - 3.0×IQR  OR  value > Q3 + 3.0×IQR  →  iqr_flag = 2 (Critical)
elif value < Q1 - 1.5×IQR  OR  value > Q3 + 1.5×IQR  →  iqr_flag = 1 (Warning)
else  →  iqr_flag = 0 (Normal)
```

### Step 4: Combined Score
```
anomaly_score = max(z_flag, iqr_flag)
```

## Account Risk Score

Individual metric anomaly scores are combined into an **Account Risk Score** (0-100):

```
risk_score = Σ (anomaly_score_i × 50 × weight_i)
```

### Metric Weights

| Metric | Weight | Rationale |
|--------|--------|-----------|
| Acceptance Rate | 30% | Strongest signal of shadow-ban risk |
| Reply Rate | 25% | Key indicator of outreach quality |
| Ghosting Rate | 20% | Early warning of audience disengagement |
| Utilisation | 15% | Operational efficiency signal |
| Activity Volume | 10% | Context signal for interpretation |
| **Total** | **100%** | |

### Risk Level Mapping

| Score Range | Level | Action |
|-------------|-------|--------|
| 0 – 30 | 🟢 Green | Healthy. Maintain current capacity. |
| 31 – 60 | 🟡 Amber | Caution. Reduce capacity to 80% of tier ceiling. |
| 61 – 100 | 🔴 Red | Critical. Halve capacity. Immediate review. |

## Capacity Recommendation Rules

```
if risk_level == "Green":
    recommended = tier_ceiling × 1.0  (100%)
elif risk_level == "Amber":
    recommended = tier_ceiling × 0.8  (80%)
elif risk_level == "Red":
    recommended = tier_ceiling × 0.5  (50%)

# Hard constraint: never exceed tier ceiling from Part 1
recommended = min(recommended, tier_ceiling)
```

## Assumptions

1. **Stationarity within windows:** Outreach metrics are approximately stationary within 14-day rolling windows. Seasonal effects (e.g., holiday periods) may violate this assumption.

2. **Normal approximation:** Z-Score assumes approximate normality. For small samples (< 30 days), the IQR method compensates by providing a distribution-free fallback.

3. **Independence of daily observations:** Daily outreach counts are treated as independent. In reality, there may be autocorrelation (e.g., a bad day followed by another bad day due to shadow-banning).

4. **Tier ceiling as hard constraint:** Recommended capacity never exceeds the tier ceiling from Part 1, regardless of observed performance.

## Confidence Levels

- **Z-Score thresholds:**
  - Z ≥ 2.0 (Warning): ~95% confidence that the value differs from baseline
  - Z ≥ 3.0 (Critical): ~99.7% confidence

- **IQR thresholds:**
  - 1.5×IQR (Warning): Conventional outlier detection boundary
  - 3.0×IQR (Critical): Extreme outlier boundary

## Known Limitations

1. **Cold-start problem:** New agents with < 6 days of data cannot be scored. The model returns a "Green" default with an insufficient data note.

2. **Seasonal effects:** The 14-day window does not account for weekly patterns (e.g., lower weekend activity). This could be mitigated with day-of-week normalization.

3. **Correlated metrics:** Acceptance rate and reply rate are not independent — a shadow-ban affects both. The weighted combination may double-count the same root cause.

4. **Tier misclassification:** If an agent declares the wrong tier in Part 1, the utilisation % and capacity recommendations will be miscalibrated.

5. **Small sample sizes:** With only 14 data points in the baseline, the standard deviation estimate has high variance. The IQR method partially mitigates this.
