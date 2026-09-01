"""
Staging tables and supporting tables for the pipeline.

Raw data lands in staging tables before transformation into the Star Schema.
Supporting tables include watermarks, dead-letter queue, and DQ results.
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


# ─────────────────────────────────────────────────────────────
# stg_raw_events — Raw events as received from the API/CSV
# ─────────────────────────────────────────────────────────────
class StgRawEvent(Base):
    """
    Staging table for raw outreach events before transformation.
    Preserves the original payload as JSONB for auditability.
    """
    __tablename__ = "stg_raw_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="api or csv"
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    processed: Mapped[bool] = mapped_column(default=False)
    run_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


# ─────────────────────────────────────────────────────────────
# pipeline_watermarks — Incremental loading state
# ─────────────────────────────────────────────────────────────
class PipelineWatermark(Base):
    """
    Tracks the last-synced position for each data entity.
    Used for incremental loading — only records newer than
    the watermark are fetched on subsequent runs.
    """
    __tablename__ = "pipeline_watermarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False,
        comment="e.g., outreach_events, agents, leads, campaigns"
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_record_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ─────────────────────────────────────────────────────────────
# dead_letter_queue — Failed records for manual review
# ─────────────────────────────────────────────────────────────
class DeadLetterRecord(Base):
    """
    Captures records that fail validation or loading.
    Preserves the original payload and error details for
    debugging and potential replay.
    """
    __tablename__ = "dead_letter_queue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    record_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="extractor, transformer, loader, dq_check"
    )
    run_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ─────────────────────────────────────────────────────────────
# dq_results — Data quality check history
# ─────────────────────────────────────────────────────────────
class DqResult(Base):
    """
    Records the result of each data quality check dimension
    for every pipeline run. Enables trending DQ scores over time.
    """
    __tablename__ = "dq_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    check_dimension: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="completeness, uniqueness, validity, timeliness, referential_integrity"
    )
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    composite_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Weighted composite score for this run (filled on final check)"
    )
    passed: Mapped[bool | None] = mapped_column(nullable=True)
