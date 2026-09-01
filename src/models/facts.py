"""
Fact tables for the Polluxa Analytics Star Schema.

Fact tables store measurable, quantitative data about outreach events,
daily agent activity, campaign performance, and pipeline execution.
Each fact row references dimension keys for slicing and dicing.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


# ─────────────────────────────────────────────────────────────
# fact_outreach_event — Individual outreach events (grain: one event)
# ─────────────────────────────────────────────────────────────
class FactOutreachEvent(Base):
    """
    Grain: One outreach event (invite sent, accepted, message sent,
    reply received, meeting booked, etc.)

    This is the most granular fact table — every interaction between
    an agent and a lead is recorded as a separate event.
    """

    __tablename__ = "fact_outreach_event"
    __table_args__ = (UniqueConstraint("event_source_id", name="uq_event_source_id"),)

    event_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_source_id: Mapped[str] = mapped_column(
        String(200), nullable=False, index=True, comment="Natural key from source system for idempotent upsert"
    )

    # Dimension foreign keys
    agent_key: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    lead_key: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    campaign_key: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    date_key: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    template_key: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Event attributes
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="INVITE_SENT, ACCEPTED, MESSAGE_SENT, REPLY_RECEIVED, MEETING_BOOKED",
    )
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    event_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="SUCCESS, FAILED, PENDING, WITHDRAWN"
    )
    response_time_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Time between invite/message and response, in minutes"
    )

    # Metadata
    loaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


# ─────────────────────────────────────────────────────────────
# fact_daily_agent_activity — Aggregated daily metrics per agent
# (grain: one agent × one day)
# ─────────────────────────────────────────────────────────────
class FactDailyAgentActivity(Base):
    """
    Grain: One agent per day.

    Pre-aggregated daily activity metrics for each LinkedIn agent.
    Used for trend analysis, utilisation tracking, and risk modeling.
    """

    __tablename__ = "fact_daily_agent_activity"
    __table_args__ = (UniqueConstraint("agent_key", "date_key", name="uq_agent_day"),)

    activity_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Dimension foreign keys
    agent_key: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    date_key: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Activity counts
    invites_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invites_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    messages_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replies_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meetings_booked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Computed rates (stored for query performance)
    acceptance_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    reply_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    utilisation_pct: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="invites_sent / daily_invite_limit from agent tier"
    )

    # Risk / anomaly (populated by Part 5 analytics)
    anomaly_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="0=normal, 1=warning, 2=critical — from anomaly detector"
    )

    # Metadata
    loaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


# ─────────────────────────────────────────────────────────────
# fact_campaign_performance — Campaign-level metrics per day
# (grain: one campaign × one day)
# ─────────────────────────────────────────────────────────────
class FactCampaignPerformance(Base):
    """
    Grain: One campaign per day.

    Aggregated performance metrics for each outreach campaign,
    used for ROI analysis and campaign comparison.
    """

    __tablename__ = "fact_campaign_performance"
    __table_args__ = (UniqueConstraint("campaign_key", "date_key", name="uq_campaign_day"),)

    perf_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Dimension foreign keys
    campaign_key: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    date_key: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Campaign metrics
    total_leads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invites_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    connected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meetings_booked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Computed rates
    conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Metadata
    loaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


# ─────────────────────────────────────────────────────────────
# fact_pipeline_run — Pipeline execution metadata
# (grain: one pipeline run)
# ─────────────────────────────────────────────────────────────
class FactPipelineRun(Base):
    """
    Grain: One pipeline execution.

    Records metadata about every pipeline run for auditability,
    performance monitoring, and observability.
    """

    __tablename__ = "fact_pipeline_run"

    run_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Timing
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Row counts
    rows_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="RUNNING", comment="RUNNING, SUCCESS, FAILED, PARTIAL"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Data Quality
    dq_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    dq_passed: Mapped[bool | None] = mapped_column(nullable=True)
