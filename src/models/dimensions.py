"""
Dimension tables for the Polluxa Analytics Star Schema.

Dimension tables provide the descriptive context for fact table measures.
SCD Type 2 is implemented for dim_agent and dim_lead to track historical changes.
SCD Type 1 (overwrite) is used for relatively static dimensions.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


# ─────────────────────────────────────────────────────────────
# dim_account_tier — LinkedIn account age risk tiers
# SCD Type 1 (static reference data from Polluxa)
# ─────────────────────────────────────────────────────────────
class DimAccountTier(Base):
    """
    Reference dimension for LinkedIn account age tiers and their
    associated daily rate limits. Directly maps to the Account Age →
    Daily Limit Matrix from Part 1 of the assessment.
    """
    __tablename__ = "dim_account_tier"

    tier_key: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tier_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    risk_classification: Mapped[str] = mapped_column(String(50), nullable=False)
    daily_invite_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_message_limit: Mapped[int] = mapped_column(Integer, nullable=False)


# ─────────────────────────────────────────────────────────────
# dim_agent — LinkedIn agents (connected accounts)
# SCD Type 2: tracks status changes (Active/Paused/Ghost) and
# tier changes with valid_from, valid_to, is_current
# ─────────────────────────────────────────────────────────────
class DimAgent(Base):
    """
    Dimension table for LinkedIn agents (connected accounts).
    Each row represents a version of an agent's state. When an agent's
    status or tier changes, the current row is closed (valid_to set)
    and a new row is inserted.
    """
    __tablename__ = "dim_agent"
    __table_args__ = (
        UniqueConstraint("agent_id", "valid_from", name="uq_agent_version"),
    )

    agent_key: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    linkedin_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    tier_key: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # SCD Type 2 tracking columns
    valid_from: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ─────────────────────────────────────────────────────────────
# dim_lead — Outreach leads / prospects
# SCD Type 2: tracks segment and status changes over time
# ─────────────────────────────────────────────────────────────
class DimLead(Base):
    """
    Dimension table for outreach leads (prospects).
    Tracks changes in segment assignment and lead status over time.
    """
    __tablename__ = "dim_lead"
    __table_args__ = (
        UniqueConstraint("lead_id", "valid_from", name="uq_lead_version"),
    )

    lead_key: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    segment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lead_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # SCD Type 2 tracking columns
    valid_from: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ─────────────────────────────────────────────────────────────
# dim_campaign — Outreach campaigns
# SCD Type 1 (overwrite — campaigns are relatively static)
# ─────────────────────────────────────────────────────────────
class DimCampaign(Base):
    """
    Dimension table for outreach campaigns.
    Contains campaign metadata like name, type, and creation date.
    """
    __tablename__ = "dim_campaign"

    campaign_key: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    campaign_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_segment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, onupdate=func.now()
    )


# ─────────────────────────────────────────────────────────────
# dim_date — Calendar date dimension
# SCD Type 1 (static — pre-populated calendar)
# ─────────────────────────────────────────────────────────────
class DimDate(Base):
    """
    Calendar date dimension for time-based analysis.
    Pre-populated with dates covering the analysis period.
    """
    __tablename__ = "dim_date"

    date_key: Mapped[int] = mapped_column(Integer, primary_key=True)  # YYYYMMDD format
    full_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    month_name: Mapped[str] = mapped_column(String(20), nullable=False)
    week_of_year: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday
    day_name: Mapped[str] = mapped_column(String(20), nullable=False)
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)


# ─────────────────────────────────────────────────────────────
# dim_message_template — Message templates used in outreach
# SCD Type 1 (overwrite)
# ─────────────────────────────────────────────────────────────
class DimMessageTemplate(Base):
    """
    Dimension table for message templates used in outreach campaigns.
    Tracks which templates are used for connection requests and follow-ups.
    """
    __tablename__ = "dim_message_template"

    template_key: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
