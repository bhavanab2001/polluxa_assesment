# Polluxa LinkedIn Agent Analytics Platform

A production-ready data engineering and analytics platform built for ingesting, modeling, analyzing, and visualizing automated LinkedIn outreach data from Polluxa CRM.

---

## 🚀 Architecture Highlights

- **Data Ingestion (Part 2):** Secure, idempotent extraction supporting both Polluxa REST API and CSV/JSON batch imports with watermark tracking and dead-letter queue (DLQ) capture.
- **Star Schema Data Warehouse (Part 3):** Conformed Facts & Dimensions in PostgreSQL with SCD Type 2 tracking for agents and leads, complete with automated surrogate key resolution.
- **Automated Data Quality (Part 4):** 5-dimension test suite (Completeness, Uniqueness, Validity, Timeliness, Referential Integrity) with a composite scoring engine and historical audit trail.
- **Statistical Risk Modeling (Part 5):** Hybrid Z-Score + IQR anomaly detection to catch acceptance-rate collapse, reply decay, and ghosting, dynamically recommending daily capacity limit adjustments.
- **Power BI Dashboard (Part 6):** Full DAX measure layer across 4 core areas: Core KPIs, Account Health, Risk Intelligence, and Campaign ROI.
- **DevOps & Observability (Part 7):** Containerized via Docker Compose, automated CI/CD pipeline via GitHub Actions, structured JSON logging with correlation IDs, and multi-channel alerting (Webhook/Email).

---

## 📂 Project Structure

```
polluxa-analytics/
├── .github/workflows/ci.yml       # GitHub Actions CI/CD pipeline
├── docs/
│   ├── data_dictionary.md         # Column-by-column schema specifications
│   ├── data_flow.md               # Visual Mermaid architecture & flow diagrams
│   └── risk_model.md              # Statistical methodology & formulas
├── powerbi/
│   └── dax_measures.md            # All Power BI DAX calculations
├── scripts/
│   ├── run_pipeline.py            # CLI entry point (run, seed, dq, risk)
│   └── seed_data.py               # Realistic dataset generator with anomalies
├── src/
│   ├── alerts/notifier.py         # Webhook and email alert integration
│   ├── analytics/                 # Anomaly detector & risk scoring model
│   ├── models/                    # Star Schema definitions (SQLAlchemy)
│   ├── pipeline/                  # Extractor, Transformer, Idempotent Loader, DLQ
│   ├── quality/                   # 5-dimension DQ checks and scoring
│   ├── config.py                  # Pydantic settings management
│   └── logging_config.py          # Structured JSON logger with correlation IDs
├── tests/                         # Full automated test suite
├── Dockerfile                     # Production container image
├── docker-compose.yml             # PostgreSQL 16 + pipeline container
└── pyproject.toml                 # Project dependencies & tool configurations
```

---

## 🛠️ Quick Start & Setup

### 1. Environment Configuration
Copy the example environment file and configure your credentials:
```bash
cp .env.example .env
```

### 2. Start PostgreSQL (Docker)
If using Docker, bring up PostgreSQL:
```bash
docker-compose up -d postgres
```

### 3. Generate Seed Data
Generate realistic demo data (including outreach events and injected anomaly spikes):
```bash
python scripts/run_pipeline.py seed
```

### 4. Run the Full Pipeline
Execute the extraction, transformation, Star Schema load, daily metric aggregation, and DQ scoring:
```bash
python scripts/run_pipeline.py run
```

### 5. Run the Statistical Risk Model
Compute agent anomaly scores and capacity recommendations:
```bash
python scripts/run_pipeline.py risk
```

### 6. Run Data Quality Checks
Audit the data quality across all 5 dimensions:
```bash
python scripts/run_pipeline.py dq
```

### 7. Run Automated Tests
```bash
pytest tests/ -v
```

---

## 📊 Connecting Power BI Desktop

1. Open **Power BI Desktop**.
2. Click **Get Data** $\rightarrow$ **PostgreSQL database**.
3. **Server:** `localhost:5432` | **Database:** `polluxa_analytics`
4. Select all `dim_*`, `fact_*`, and `dq_results` tables.
5. Apply the DAX measures detailed in `powerbi/dax_measures.md` to build the 4 dashboard views.
