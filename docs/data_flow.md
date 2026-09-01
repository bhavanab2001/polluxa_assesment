# Data Flow Architecture — Polluxa Analytics Platform

## End-to-End Data Flow

```mermaid
flowchart LR
    subgraph SOURCE["Data Sources"]
        API["Polluxa REST API"]
        CSV["CSV/JSON Files"]
    end

    subgraph EXTRACT["Layer 1: Extraction"]
        EXT["Extractor\n(API Client + CSV Reader)"]
        WM["Watermark\nTracker"]
    end

    subgraph STAGING["Layer 2: Staging"]
        STG["stg_raw_events\n(JSONB Payloads)"]
    end

    subgraph TRANSFORM["Layer 3: Transformation"]
        TR["Transformer\n- Timestamp UTC\n- Type mapping\n- Null handling\n- Deduplication"]
        DLQ["Dead Letter\nQueue"]
    end

    subgraph WAREHOUSE["Layer 4: Star Schema"]
        direction TB
        DIM["Dimensions\n- dim_agent (SCD2)\n- dim_lead (SCD2)\n- dim_campaign\n- dim_date\n- dim_template\n- dim_account_tier"]
        FACT["Facts\n- fact_outreach_event\n- fact_daily_agent_activity\n- fact_campaign_performance\n- fact_pipeline_run"]
    end

    subgraph QUALITY["Layer 5: Quality"]
        DQ["DQ Checks\n(5 dimensions)"]
        SCORE["Composite\nDQ Score"]
        HIST["dq_results\n(History)"]
    end

    subgraph ANALYTICS["Layer 6: Analytics"]
        ANOMALY["Anomaly\nDetector"]
        RISK["Risk\nModel"]
        CAP["Capacity\nOptimizer"]
    end

    subgraph PRESENTATION["Layer 7: Presentation"]
        PBI["Power BI\nDashboard"]
        ALERT["Alert\nNotifier"]
    end

    API --> EXT
    CSV --> EXT
    WM -.->|incremental| EXT
    EXT --> STG
    STG --> TR
    TR -->|clean records| WAREHOUSE
    TR -->|failed records| DLQ
    DIM --> FACT
    FACT --> DQ
    DQ --> SCORE
    SCORE --> HIST
    FACT --> ANOMALY
    ANOMALY --> RISK
    RISK --> CAP
    WAREHOUSE --> PBI
    RISK --> PBI
    SCORE -->|breach| ALERT
    RISK -->|high risk| ALERT
    EXT -.->|update| WM
```

## Pipeline Execution Sequence

```mermaid
sequenceDiagram
    participant CLI as CLI / Scheduler
    participant ORC as Orchestrator
    participant EXT as Extractor
    participant WM as Watermarks
    participant TR as Transformer
    participant LDR as Loader
    participant DQ as DQ Scorer
    participant RISK as Risk Model
    participant ALERT as Notifier

    CLI->>ORC: run()
    ORC->>ORC: Generate run_id + correlation_id
    ORC->>ORC: Seed reference data (tiers, dates)

    ORC->>WM: Get last watermark
    WM-->>ORC: last_synced_at

    ORC->>EXT: Extract (since watermark)
    EXT-->>ORC: Raw records

    ORC->>TR: Transform records
    TR-->>ORC: Clean records + DLQ entries

    ORC->>LDR: Upsert to Star Schema
    LDR-->>ORC: LoadResult (inserted/updated/failed)

    ORC->>ORC: Aggregate daily metrics
    ORC->>WM: Update watermark

    ORC->>DQ: Run all checks
    DQ-->>ORC: Composite DQ score

    alt DQ Score < Threshold
        ORC->>ALERT: alert_dq_breach()
    end

    ORC->>RISK: Score all agents
    RISK-->>ORC: Agent risk profiles

    alt Agent Risk = Red
        ORC->>ALERT: alert_high_risk_agent()
    end

    ORC->>ORC: Record pipeline run metadata
    ORC-->>CLI: Summary (status, counts, score)
```

## Layer Responsibilities

| Layer | Purpose | Tables/Components |
|-------|---------|-------------------|
| **Source** | Raw data origin | Polluxa API, CSV/JSON exports |
| **Extraction** | Fetch data incrementally | `PolluaxAPIClient`, `CSVExtractor`, `pipeline_watermarks` |
| **Staging** | Preserve raw data | `stg_raw_events` (JSONB payloads) |
| **Transformation** | Clean, validate, standardize | `DataTransformer`, `DeadLetterQueue` |
| **Star Schema** | Dimensional model for analytics | 6 dimensions + 4 fact tables |
| **Quality** | Validate and score data | `DQChecks`, `DQScorer`, `dq_results` |
| **Analytics** | Detect risk and optimize | `AnomalyDetector`, `RiskModel`, capacity recommendations |
| **Presentation** | Visualize and alert | Power BI dashboard, webhook/email alerts |
