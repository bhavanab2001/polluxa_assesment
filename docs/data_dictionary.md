# Data Dictionary — Polluxa Analytics Platform

> Complete column-level documentation for all Star Schema tables.

---

## Dimension Tables

### dim_account_tier
Reference dimension for LinkedIn account age tiers and daily rate limits.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `tier_key` | INTEGER (PK) | No | Surrogate key (auto-increment) |
| `tier_name` | VARCHAR(50) | No | Account age tier label (e.g., "< 1 Month", "1+ Year") |
| `risk_classification` | VARCHAR(50) | No | Risk level (Very High Risk, High Risk, Moderate Risk, Low Risk, Minimal Risk) |
| `daily_invite_limit` | INTEGER | No | Maximum connection invitations per day for this tier |
| `daily_message_limit` | INTEGER | No | Maximum messages per day for this tier |

---

### dim_agent *(SCD Type 2)*
LinkedIn agents (connected accounts). Each row represents a version of an agent's state.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `agent_key` | INTEGER (PK) | No | Surrogate key (auto-increment) |
| `agent_id` | VARCHAR(100) | No | Natural key — unique agent identifier from Polluxa |
| `linkedin_email` | VARCHAR(255) | Yes | LinkedIn account email address |
| `display_name` | VARCHAR(255) | Yes | Agent display name |
| `status` | VARCHAR(50) | No | Current status: `active`, `paused`, `ghost`, `connected` |
| `tier_key` | INTEGER (FK) | Yes | References `dim_account_tier.tier_key` |
| `valid_from` | DATETIME | No | SCD2: Start of this version's validity period |
| `valid_to` | DATETIME | Yes | SCD2: End of this version's validity (NULL if current) |
| `is_current` | BOOLEAN | No | SCD2: `true` if this is the active version |

---

### dim_lead *(SCD Type 2)*
Outreach leads (prospects) targeted by campaigns.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `lead_key` | INTEGER (PK) | No | Surrogate key (auto-increment) |
| `lead_id` | VARCHAR(100) | No | Natural key — unique lead identifier from Polluxa |
| `full_name` | VARCHAR(255) | Yes | Lead's full name |
| `company` | VARCHAR(255) | Yes | Lead's company/organization name |
| `title` | VARCHAR(255) | Yes | Job title |
| `linkedin_url` | VARCHAR(500) | Yes | LinkedIn profile URL |
| `segment` | VARCHAR(100) | Yes | Target segment (e.g., "Tech Founders", "Sales Leaders") |
| `lead_status` | VARCHAR(50) | Yes | Funnel status: `new`, `contacted`, `connected`, `replied`, `qualified`, `meeting_booked` |
| `valid_from` | DATETIME | No | SCD2: Start of this version's validity period |
| `valid_to` | DATETIME | Yes | SCD2: End of validity (NULL if current) |
| `is_current` | BOOLEAN | No | SCD2: `true` if this is the active version |

---

### dim_campaign
Outreach campaigns.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `campaign_key` | INTEGER (PK) | No | Surrogate key (auto-increment) |
| `campaign_id` | VARCHAR(100) | No | Natural key — unique campaign ID from Polluxa |
| `campaign_name` | VARCHAR(255) | Yes | Human-readable campaign name |
| `campaign_type` | VARCHAR(100) | Yes | Campaign type (e.g., `connection_request`, `inmail`) |
| `target_segment` | VARCHAR(100) | Yes | Target audience segment |
| `created_at` | DATETIME | Yes | When the campaign was created |
| `updated_at` | DATETIME | Yes | Last modification timestamp |

---

### dim_date
Calendar date dimension for time-based analysis.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `date_key` | INTEGER (PK) | No | Date in YYYYMMDD format (e.g., 20260815) |
| `full_date` | DATE | No | The actual date value |
| `year` | INTEGER | No | Calendar year |
| `quarter` | INTEGER | No | Quarter (1-4) |
| `month` | INTEGER | No | Month (1-12) |
| `month_name` | VARCHAR(20) | No | Full month name (e.g., "August") |
| `week_of_year` | INTEGER | No | ISO week number (1-53) |
| `day_of_week` | INTEGER | No | Day of week (0=Monday, 6=Sunday) |
| `day_name` | VARCHAR(20) | No | Full day name (e.g., "Wednesday") |
| `is_weekend` | BOOLEAN | No | `true` for Saturday/Sunday |

---

### dim_message_template
Message templates used in outreach campaigns.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `template_key` | INTEGER (PK) | No | Surrogate key (auto-increment) |
| `template_id` | VARCHAR(100) | No | Natural key — unique template ID |
| `template_name` | VARCHAR(255) | Yes | Template display name |
| `template_body` | TEXT | Yes | Full template text with merge fields (`{{first_name}}`, etc.) |
| `channel` | VARCHAR(50) | Yes | Channel: `linkedin`, `email`, `whatsapp` |
| `created_at` | DATETIME | Yes | When the template was created |

---

## Fact Tables

### fact_outreach_event
**Grain: One outreach event (invite, accept, message, reply, meeting)**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `event_key` | BIGINT (PK) | No | Surrogate key (auto-increment) |
| `event_source_id` | VARCHAR(200) | No | Natural key from source for idempotent upsert (UNIQUE) |
| `agent_key` | INTEGER (FK) | Yes | References `dim_agent.agent_key` |
| `lead_key` | INTEGER (FK) | Yes | References `dim_lead.lead_key` |
| `campaign_key` | INTEGER (FK) | Yes | References `dim_campaign.campaign_key` |
| `date_key` | INTEGER (FK) | Yes | References `dim_date.date_key` |
| `template_key` | INTEGER (FK) | Yes | References `dim_message_template.template_key` |
| `event_type` | VARCHAR(50) | No | Event type enum: `INVITE_SENT`, `ACCEPTED`, `MESSAGE_SENT`, `REPLY_RECEIVED`, `MEETING_BOOKED`, `WITHDRAWN`, `FAILED` |
| `event_timestamp` | DATETIME | No | When the event occurred (UTC) |
| `event_status` | VARCHAR(50) | Yes | Outcome: `SUCCESS`, `FAILED`, `PENDING`, `WITHDRAWN` |
| `response_time_minutes` | INTEGER | Yes | Time between action and response, in minutes |
| `loaded_at` | DATETIME | No | When the record was loaded into the warehouse |

---

### fact_daily_agent_activity
**Grain: One agent × one day**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `activity_key` | BIGINT (PK) | No | Surrogate key (auto-increment) |
| `agent_key` | INTEGER (FK) | No | References `dim_agent.agent_key` |
| `date_key` | INTEGER (FK) | No | References `dim_date.date_key` |
| `invites_sent` | INTEGER | No | Number of connection invitations sent |
| `invites_accepted` | INTEGER | No | Number of invitations accepted |
| `messages_sent` | INTEGER | No | Number of messages sent |
| `replies_received` | INTEGER | No | Number of replies received |
| `meetings_booked` | INTEGER | No | Number of meetings booked |
| `acceptance_rate` | FLOAT | Yes | `invites_accepted / invites_sent` (0-1 scale) |
| `reply_rate` | FLOAT | Yes | `replies_received / invites_accepted` (0-1 scale) |
| `utilisation_pct` | FLOAT | Yes | `invites_sent / daily_invite_limit` (0-1+ scale) |
| `anomaly_score` | FLOAT | Yes | Risk anomaly score: 0=normal, 1=warning, 2=critical |
| `loaded_at` | DATETIME | No | When the record was loaded/updated |

---

### fact_campaign_performance
**Grain: One campaign × one day**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `perf_key` | BIGINT (PK) | No | Surrogate key (auto-increment) |
| `campaign_key` | INTEGER (FK) | No | References `dim_campaign.campaign_key` |
| `date_key` | INTEGER (FK) | No | References `dim_date.date_key` |
| `total_leads` | INTEGER | No | Distinct leads targeted |
| `invites_sent` | INTEGER | No | Connection invitations sent |
| `connected` | INTEGER | No | Connections accepted |
| `replied` | INTEGER | No | Replies received |
| `meetings_booked` | INTEGER | No | Meetings booked |
| `conversion_rate` | FLOAT | Yes | `meetings_booked / invites_sent` (0-1 scale) |
| `roi_score` | FLOAT | Yes | Composite ROI metric |
| `loaded_at` | DATETIME | No | When the record was loaded/updated |

---

### fact_pipeline_run
**Grain: One pipeline execution**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `run_key` | BIGINT (PK) | No | Surrogate key (auto-increment) |
| `run_id` | VARCHAR(100) | No | Unique run identifier (UNIQUE) |
| `correlation_id` | VARCHAR(100) | Yes | Logging correlation ID for traceability |
| `start_time` | DATETIME | No | Pipeline run start timestamp |
| `end_time` | DATETIME | Yes | Pipeline run end timestamp |
| `duration_seconds` | FLOAT | Yes | Total execution duration |
| `rows_extracted` | INTEGER | No | Total rows extracted from source |
| `rows_loaded` | INTEGER | No | Total rows successfully loaded |
| `rows_failed` | INTEGER | No | Total rows that failed processing |
| `rows_skipped` | INTEGER | No | Rows skipped (already exists, unchanged) |
| `status` | VARCHAR(50) | No | Run outcome: `RUNNING`, `SUCCESS`, `FAILED`, `PARTIAL` |
| `error_message` | TEXT | Yes | Error details if failed |
| `dq_score` | FLOAT | Yes | Composite data quality score (0-100) |
| `dq_passed` | BOOLEAN | Yes | Whether the DQ score met the threshold |

---

## Supporting Tables

### pipeline_watermarks
Tracks incremental loading position per entity.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER (PK) | No | Auto-increment |
| `entity_name` | VARCHAR(100) | No | Entity name (UNIQUE): `agents`, `leads`, `campaigns`, `outreach_events` |
| `last_synced_at` | DATETIME | Yes | Timestamp of last successful sync |
| `last_record_id` | VARCHAR(200) | Yes | ID of last synced record |
| `updated_at` | DATETIME | No | When the watermark was last updated |

### dead_letter_queue
Captures records that fail validation or loading.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGINT (PK) | No | Auto-increment |
| `source_id` | VARCHAR(200) | Yes | Original record identifier |
| `record_payload` | JSONB | No | Full original record as JSON |
| `error_message` | TEXT | No | Description of the failure |
| `error_type` | VARCHAR(100) | Yes | Error classification |
| `source` | VARCHAR(100) | Yes | Pipeline stage: `extractor`, `transformer`, `loader`, `dq_check` |
| `run_id` | VARCHAR(100) | Yes | Pipeline run ID for traceability |
| `created_at` | DATETIME | No | When the record was dead-lettered |
| `resolved` | BOOLEAN | No | Whether the issue has been reviewed/fixed |
| `resolved_at` | DATETIME | Yes | When the issue was resolved |

### dq_results
Data quality check results history.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGINT (PK) | No | Auto-increment |
| `run_id` | VARCHAR(100) | No | Pipeline run ID |
| `check_dimension` | VARCHAR(50) | No | DQ dimension: `completeness`, `uniqueness`, `validity`, `timeliness`, `referential_integrity` |
| `table_name` | VARCHAR(100) | No | Table that was checked |
| `score` | FLOAT | No | Individual check score (0-100) |
| `weight` | FLOAT | No | Weight used in composite calculation |
| `details` | JSONB | Yes | Detailed check results and failure specifics |
| `checked_at` | DATETIME | No | When the check was run |
| `composite_score` | FLOAT | Yes | Overall composite DQ score for this run |
| `passed` | BOOLEAN | Yes | Whether the composite score met the threshold |
