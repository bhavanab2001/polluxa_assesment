# Power BI DAX Measures — Polluxa Analytics Dashboard

> All measures are explicit DAX — no implicit aggregations.

## Connection Setup

1. Open Power BI Desktop
2. **Get Data → PostgreSQL Database**
3. Server: `localhost` (or Docker host), Port: `5432`
4. Database: `polluxa_analytics`
5. Import all tables: `dim_*`, `fact_*`, `dq_results`
6. Set up relationships per the Star Schema in `docs/data_flow.md`

---

## Page 1: Core KPIs Overview

### Cards

```dax
Total Invites Sent =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "INVITE_SENT"
)

Total Accepted =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "ACCEPTED"
)

Acceptance Rate =
DIVIDE(
    [Total Accepted],
    [Total Invites Sent],
    0
)

Reply Rate =
DIVIDE(
    CALCULATE(
        COUNTROWS(fact_outreach_event),
        fact_outreach_event[event_type] = "REPLY_RECEIVED"
    ),
    [Total Accepted],
    0
)

Conversion Rate =
DIVIDE(
    CALCULATE(
        COUNTROWS(fact_outreach_event),
        fact_outreach_event[event_type] = "MEETING_BOOKED"
    ),
    [Total Invites Sent],
    0
)

Total Meetings Booked =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "MEETING_BOOKED"
)
```

### Throughput vs Limits (Line Chart)

```dax
Daily Invites Sent =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "INVITE_SENT"
)

Daily Invite Limit =
MAX(dim_account_tier[daily_invite_limit])

Utilisation % =
DIVIDE(
    [Daily Invites Sent],
    [Daily Invite Limit],
    0
)
```

### Funnel (Bar Chart)

```dax
Funnel - Sent =
[Total Invites Sent]

Funnel - Accepted =
[Total Accepted]

Funnel - Replied =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "REPLY_RECEIVED"
)

Funnel - Meeting Booked =
[Total Meetings Booked]
```

---

## Page 2: Account Health

### Agent Status Table

```dax
Agent Status =
IF(
    RELATED(dim_agent[status]) = "active",
    "🟢 Active",
    IF(
        RELATED(dim_agent[status]) = "paused",
        "🟡 Paused",
        "👻 Ghost"
    )
)

Days Since Last Activity =
DATEDIFF(
    CALCULATE(
        MAX(fact_outreach_event[event_timestamp]),
        ALLEXCEPT(fact_outreach_event, fact_outreach_event[agent_key])
    ),
    TODAY(),
    DAY
)

Agent Utilisation % =
DIVIDE(
    CALCULATE(SUM(fact_daily_agent_activity[invites_sent])),
    CALCULATE(SUM(dim_account_tier[daily_invite_limit])) *
        DISTINCTCOUNT(fact_daily_agent_activity[date_key]),
    0
)
```

### Status Donut Chart

```dax
Active Agent Count =
CALCULATE(
    DISTINCTCOUNT(dim_agent[agent_id]),
    dim_agent[status] = "active",
    dim_agent[is_current] = TRUE()
)

Paused Agent Count =
CALCULATE(
    DISTINCTCOUNT(dim_agent[agent_id]),
    dim_agent[status] = "paused",
    dim_agent[is_current] = TRUE()
)

Ghost Agent Count =
CALCULATE(
    DISTINCTCOUNT(dim_agent[agent_id]),
    dim_agent[status] = "ghost",
    dim_agent[is_current] = TRUE()
)
```

---

## Page 3: Risk Intelligence

### Platform Risk Gauge

```dax
Platform Average Risk Score =
AVERAGE(fact_daily_agent_activity[anomaly_score]) * 50

Risk Level Label =
SWITCH(
    TRUE(),
    [Platform Average Risk Score] <= 30, "🟢 Low Risk",
    [Platform Average Risk Score] <= 60, "🟡 Moderate Risk",
    "🔴 High Risk"
)
```

### Agent Risk Heat Map

```dax
Agent Risk Score =
CALCULATE(
    MAX(fact_daily_agent_activity[anomaly_score]) * 50,
    LASTDATE(dim_date[full_date])
)

Risk Threshold Warning = 30
Risk Threshold Critical = 60
```

### Recommended Capacity Table

```dax
Current Tier Limit =
MAX(dim_account_tier[daily_invite_limit])

Recommended Invites =
VAR RiskScore = [Agent Risk Score]
RETURN
SWITCH(
    TRUE(),
    RiskScore <= 30, [Current Tier Limit],
    RiskScore <= 60, ROUND([Current Tier Limit] * 0.8, 0),
    ROUND([Current Tier Limit] * 0.5, 0)
)

Capacity Adjustment % =
DIVIDE([Recommended Invites], [Current Tier Limit], 0) - 1
```

---

## Page 4: Campaign ROI

### Campaign Comparison (Stacked Bar)

```dax
Campaign Invites Sent =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "INVITE_SENT"
)

Campaign Connected =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "ACCEPTED"
)

Campaign Replied =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "REPLY_RECEIVED"
)

Campaign Meetings =
CALCULATE(
    COUNTROWS(fact_outreach_event),
    fact_outreach_event[event_type] = "MEETING_BOOKED"
)
```

### Campaign ROI Score

```dax
Campaign ROI Score =
VAR Sent = [Campaign Invites Sent]
VAR Meetings = [Campaign Meetings]
VAR AcceptRate = DIVIDE([Campaign Connected], Sent, 0)
VAR ReplyRate = DIVIDE([Campaign Replied], [Campaign Connected], 0)
VAR ConvRate = DIVIDE(Meetings, Sent, 0)
RETURN
    (AcceptRate * 0.3 + ReplyRate * 0.3 + ConvRate * 0.4) * 100
```

### Acceptance vs Reply Scatter

```dax
Segment Acceptance Rate =
DIVIDE(
    CALCULATE(COUNTROWS(fact_outreach_event), fact_outreach_event[event_type] = "ACCEPTED"),
    CALCULATE(COUNTROWS(fact_outreach_event), fact_outreach_event[event_type] = "INVITE_SENT"),
    0
)

Segment Reply Rate =
DIVIDE(
    CALCULATE(COUNTROWS(fact_outreach_event), fact_outreach_event[event_type] = "REPLY_RECEIVED"),
    CALCULATE(COUNTROWS(fact_outreach_event), fact_outreach_event[event_type] = "ACCEPTED"),
    0
)
```

---

## DQ Trend (Optional Page 5)

```dax
Latest DQ Score =
CALCULATE(
    MAX(dq_results[composite_score]),
    LASTDATE(dq_results[checked_at])
)

DQ Trend =
CALCULATE(
    AVERAGE(dq_results[composite_score]),
    ALLEXCEPT(dq_results, dq_results[checked_at])
)

DQ Pass/Fail =
IF([Latest DQ Score] >= 85, "✅ Pass", "❌ Fail")
```
