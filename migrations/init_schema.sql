-- ============================================================
-- Polluxa Analytics Platform — Star Schema DDL (PostgreSQL)
-- ============================================================

-- 1. Reference: Account Age Tiers & Rate Limits
CREATE TABLE IF NOT EXISTS dim_account_tier (
    tier_key SERIAL PRIMARY KEY,
    tier_name VARCHAR(50) UNIQUE NOT NULL,
    risk_classification VARCHAR(50) NOT NULL,
    daily_invite_limit INT NOT NULL,
    daily_message_limit INT NOT NULL
);

-- Seed Account Age Matrix from Assessment Part 1
INSERT INTO dim_account_tier (tier_name, risk_classification, daily_invite_limit, daily_message_limit)
VALUES 
    ('< 1 Month', 'Very High Risk', 5, 10),
    ('1 Month', 'High Risk', 10, 15),
    ('2-6 Months', 'Moderate Risk', 15, 25),
    ('6-12 Months', 'Low Risk', 25, 40),
    ('1+ Year', 'Minimal Risk', 30, 60)
ON CONFLICT (tier_name) DO NOTHING;

-- 2. Dimension: LinkedIn Agents (SCD Type 2)
CREATE TABLE IF NOT EXISTS dim_agent (
    agent_key SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) NOT NULL,
    linkedin_email VARCHAR(255),
    display_name VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    tier_key INT REFERENCES dim_account_tier(tier_key),
    valid_from TIMESTAMP NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMP,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_agent_version UNIQUE (agent_id, valid_from)
);
CREATE INDEX IF NOT EXISTS idx_dim_agent_id ON dim_agent(agent_id);

-- 3. Dimension: Outreach Leads (SCD Type 2)
CREATE TABLE IF NOT EXISTS dim_lead (
    lead_key SERIAL PRIMARY KEY,
    lead_id VARCHAR(100) NOT NULL,
    full_name VARCHAR(255),
    company VARCHAR(255),
    title VARCHAR(255),
    linkedin_url VARCHAR(500),
    segment VARCHAR(100),
    lead_status VARCHAR(50),
    valid_from TIMESTAMP NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMP,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_lead_version UNIQUE (lead_id, valid_from)
);
CREATE INDEX IF NOT EXISTS idx_dim_lead_id ON dim_lead(lead_id);

-- 4. Dimension: Campaigns (SCD Type 1)
CREATE TABLE IF NOT EXISTS dim_campaign (
    campaign_key SERIAL PRIMARY KEY,
    campaign_id VARCHAR(100) UNIQUE NOT NULL,
    campaign_name VARCHAR(255),
    campaign_type VARCHAR(100),
    target_segment VARCHAR(100),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 5. Dimension: Calendar Date
CREATE TABLE IF NOT EXISTS dim_date (
    date_key INT PRIMARY KEY, -- Format: YYYYMMDD
    full_date DATE UNIQUE NOT NULL,
    year INT NOT NULL,
    quarter INT NOT NULL,
    month INT NOT NULL,
    month_name VARCHAR(20) NOT NULL,
    week_of_year INT NOT NULL,
    day_of_week INT NOT NULL,
    day_name VARCHAR(20) NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

-- 6. Dimension: Message Templates
CREATE TABLE IF NOT EXISTS dim_message_template (
    template_key SERIAL PRIMARY KEY,
    template_id VARCHAR(100) UNIQUE NOT NULL,
    template_name VARCHAR(255),
    template_body TEXT,
    channel VARCHAR(50),
    created_at TIMESTAMP
);

-- 7. Fact: Granular Outreach Events
CREATE TABLE IF NOT EXISTS fact_outreach_event (
    event_key BIGSERIAL PRIMARY KEY,
    event_source_id VARCHAR(200) UNIQUE NOT NULL,
    agent_key INT REFERENCES dim_agent(agent_key),
    lead_key INT REFERENCES dim_lead(lead_key),
    campaign_key INT REFERENCES dim_campaign(campaign_key),
    date_key INT REFERENCES dim_date(date_key),
    template_key INT REFERENCES dim_message_template(template_key),
    event_type VARCHAR(50) NOT NULL,
    event_timestamp TIMESTAMP NOT NULL,
    event_status VARCHAR(50),
    response_time_minutes INT,
    loaded_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fact_event_type ON fact_outreach_event(event_type);
CREATE INDEX IF NOT EXISTS idx_fact_event_time ON fact_outreach_event(event_timestamp);

-- 8. Fact: Daily Agent Activity Aggregates
CREATE TABLE IF NOT EXISTS fact_daily_agent_activity (
    activity_key BIGSERIAL PRIMARY KEY,
    agent_key INT NOT NULL,
    date_key INT NOT NULL,
    invites_sent INT NOT NULL DEFAULT 0,
    invites_accepted INT NOT NULL DEFAULT 0,
    messages_sent INT NOT NULL DEFAULT 0,
    replies_received INT NOT NULL DEFAULT 0,
    meetings_booked INT NOT NULL DEFAULT 0,
    acceptance_rate FLOAT,
    reply_rate FLOAT,
    utilisation_pct FLOAT,
    anomaly_score FLOAT,
    loaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_day UNIQUE (agent_key, date_key)
);

-- 9. Fact: Campaign Performance Aggregates
CREATE TABLE IF NOT EXISTS fact_campaign_performance (
    perf_key BIGSERIAL PRIMARY KEY,
    campaign_key INT NOT NULL,
    date_key INT NOT NULL,
    total_leads INT NOT NULL DEFAULT 0,
    invites_sent INT NOT NULL DEFAULT 0,
    connected INT NOT NULL DEFAULT 0,
    replied INT NOT NULL DEFAULT 0,
    meetings_booked INT NOT NULL DEFAULT 0,
    conversion_rate FLOAT,
    roi_score FLOAT,
    loaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_campaign_day UNIQUE (campaign_key, date_key)
);

-- 10. Fact: Pipeline Run Audit Log
CREATE TABLE IF NOT EXISTS fact_pipeline_run (
    run_key BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(100) UNIQUE NOT NULL,
    correlation_id VARCHAR(100),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds FLOAT,
    rows_extracted INT NOT NULL DEFAULT 0,
    rows_loaded INT NOT NULL DEFAULT 0,
    rows_failed INT NOT NULL DEFAULT 0,
    rows_skipped INT NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'RUNNING',
    error_message TEXT,
    dq_score FLOAT,
    dq_passed BOOLEAN
);

-- 11. Supporting: Incremental Watermarks
CREATE TABLE IF NOT EXISTS pipeline_watermarks (
    id SERIAL PRIMARY KEY,
    entity_name VARCHAR(100) UNIQUE NOT NULL,
    last_synced_at TIMESTAMP,
    last_record_id VARCHAR(200),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 12. Supporting: Dead-Letter Queue
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(200),
    record_payload JSONB NOT NULL,
    error_message TEXT NOT NULL,
    error_type VARCHAR(100),
    source VARCHAR(100),
    run_id VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP
);

-- 13. Supporting: Data Quality Results History
CREATE TABLE IF NOT EXISTS dq_results (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(100) NOT NULL,
    check_dimension VARCHAR(50) NOT NULL,
    table_name VARCHAR(100) NOT NULL,
    score FLOAT NOT NULL,
    weight FLOAT NOT NULL,
    details JSONB,
    checked_at TIMESTAMP NOT NULL DEFAULT NOW(),
    composite_score FLOAT,
    passed BOOLEAN
);
