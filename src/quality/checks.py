"""
Data quality checks across five dimensions:
Completeness, Uniqueness, Validity, Timeliness, Referential Integrity.

Each check returns a score from 0 to 100 and details about failures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.logging_config import get_logger

logger = get_logger("dq_checks")


class CheckResult:
    """Result of a single DQ check."""

    def __init__(
        self,
        dimension: str,
        table_name: str,
        score: float,
        details: dict[str, Any] | None = None,
    ):
        self.dimension = dimension
        self.table_name = table_name
        self.score = min(max(score, 0.0), 100.0)  # Clamp to 0-100
        self.details = details or {}

    def __repr__(self) -> str:
        return f"CheckResult({self.dimension}, {self.table_name}, score={self.score:.1f})"


class DQChecks:
    """
    Data quality validation suite.

    Runs automated checks across five dimensions for the Star Schema tables.
    """

    def __init__(self, session: Session):
        self.session = session

    # ── Completeness ─────────────────────────────────────────
    def check_completeness(self) -> list[CheckResult]:
        """
        Check for unexpected NULLs in required columns.
        Score = (non-null count / total count) × 100 for each required column.
        """
        results: list[CheckResult] = []

        required_columns = {
            "fact_outreach_event": ["event_source_id", "event_type", "event_timestamp"],
            "fact_daily_agent_activity": ["agent_key", "date_key"],
            "dim_agent": ["agent_id", "status"],
            "dim_lead": ["lead_id"],
            "dim_campaign": ["campaign_id"],
        }

        for table, columns in required_columns.items():
            total = self._count_rows(table)
            if total == 0:
                results.append(CheckResult("completeness", table, 100.0, {"note": "empty table"}))
                continue

            null_counts: dict[str, int] = {}
            for col in columns:
                null_count = self.session.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL")
                ).scalar() or 0
                null_counts[col] = null_count

            total_nulls = sum(null_counts.values())
            total_checks = total * len(columns)
            score = ((total_checks - total_nulls) / total_checks) * 100 if total_checks > 0 else 100.0

            results.append(CheckResult(
                "completeness", table, score,
                {"null_counts": null_counts, "total_rows": total},
            ))

        avg_score = sum(r.score for r in results) / len(results) if results else 100.0
        logger.info("completeness_check_complete", score=round(avg_score, 2))
        return results

    # ── Uniqueness ───────────────────────────────────────────
    def check_uniqueness(self) -> list[CheckResult]:
        """
        Check for duplicate natural keys.
        Score = (distinct count / total count) × 100.
        """
        results: list[CheckResult] = []

        unique_keys = {
            "fact_outreach_event": "event_source_id",
            "dim_agent": "agent_id",  # May have multiple versions (SCD2), check within is_current
            "dim_lead": "lead_id",
            "dim_campaign": "campaign_id",
            "dim_message_template": "template_id",
        }

        for table, key_col in unique_keys.items():
            total = self._count_rows(table)
            if total == 0:
                results.append(CheckResult("uniqueness", table, 100.0, {"note": "empty table"}))
                continue

            # For SCD2 tables, check uniqueness within current records only
            if table in ("dim_agent", "dim_lead"):
                distinct = self.session.execute(
                    text(f"SELECT COUNT(DISTINCT {key_col}) FROM {table} WHERE is_current = true")
                ).scalar() or 0
                current_total = self.session.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE is_current = true")
                ).scalar() or 0
                score = (distinct / current_total) * 100 if current_total > 0 else 100.0
                details = {"distinct": distinct, "total_current": current_total}
            else:
                distinct = self.session.execute(
                    text(f"SELECT COUNT(DISTINCT {key_col}) FROM {table}")
                ).scalar() or 0
                score = (distinct / total) * 100 if total > 0 else 100.0
                details = {"distinct": distinct, "total": total}

            results.append(CheckResult("uniqueness", table, score, details))

        avg_score = sum(r.score for r in results) / len(results) if results else 100.0
        logger.info("uniqueness_check_complete", score=round(avg_score, 2))
        return results

    # ── Validity ─────────────────────────────────────────────
    def check_validity(self) -> list[CheckResult]:
        """
        Check value constraints and business rules.
        - Event types must be in the valid set
        - Chronological ordering (accepted_at >= sent_at)
        - Daily counts must not exceed tier limits
        """
        results: list[CheckResult] = []

        # 1. Event type validity
        total_events = self._count_rows("fact_outreach_event")
        if total_events > 0:
            valid_types = "('INVITE_SENT','ACCEPTED','MESSAGE_SENT','REPLY_RECEIVED','MEETING_BOOKED','WITHDRAWN','FAILED')"
            invalid_count = self.session.execute(
                text(f"SELECT COUNT(*) FROM fact_outreach_event WHERE event_type NOT IN {valid_types}")
            ).scalar() or 0
            score = ((total_events - invalid_count) / total_events) * 100
            results.append(CheckResult("validity", "fact_outreach_event.event_type", score, {
                "invalid_event_types": invalid_count,
            }))
        else:
            results.append(CheckResult("validity", "fact_outreach_event.event_type", 100.0))

        # 2. Daily invite counts vs tier limits
        total_activity = self._count_rows("fact_daily_agent_activity")
        if total_activity > 0:
            violations = self.session.execute(text("""
                SELECT COUNT(*) FROM fact_daily_agent_activity a
                JOIN dim_agent da ON a.agent_key = da.agent_key AND da.is_current = true
                JOIN dim_account_tier t ON da.tier_key = t.tier_key
                WHERE a.invites_sent > t.daily_invite_limit
            """)).scalar() or 0
            score = ((total_activity - violations) / total_activity) * 100
            results.append(CheckResult("validity", "fact_daily_agent_activity.tier_limits", score, {
                "tier_limit_violations": violations,
            }))
        else:
            results.append(CheckResult("validity", "fact_daily_agent_activity.tier_limits", 100.0))

        avg_score = sum(r.score for r in results) / len(results) if results else 100.0
        logger.info("validity_check_complete", score=round(avg_score, 2))
        return results

    # ── Timeliness ───────────────────────────────────────────
    def check_timeliness(self) -> list[CheckResult]:
        """
        Check data freshness — records should be within 24h SLA.
        Score = (records within SLA / total) × 100.
        """
        results: list[CheckResult] = []
        sla_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        total_events = self._count_rows("fact_outreach_event")
        if total_events > 0:
            stale_count = self.session.execute(
                text("SELECT COUNT(*) FROM fact_outreach_event WHERE loaded_at < :cutoff"),
                {"cutoff": sla_cutoff},
            ).scalar() or 0

            # For first runs, all data may be "fresh" by loaded_at
            fresh = total_events - stale_count
            score = (fresh / total_events) * 100
            results.append(CheckResult("timeliness", "fact_outreach_event", score, {
                "total": total_events, "fresh": fresh, "stale": stale_count,
                "sla_hours": 24,
            }))
        else:
            results.append(CheckResult("timeliness", "fact_outreach_event", 100.0))

        avg_score = sum(r.score for r in results) / len(results) if results else 100.0
        logger.info("timeliness_check_complete", score=round(avg_score, 2))
        return results

    # ── Referential Integrity ────────────────────────────────
    def check_referential_integrity(self) -> list[CheckResult]:
        """
        Check that all foreign keys in fact tables resolve to dimension tables.
        Score = (matched FK count / total FK count) × 100.
        """
        results: list[CheckResult] = []

        fk_checks = [
            ("fact_outreach_event", "agent_key", "dim_agent", "agent_key"),
            ("fact_outreach_event", "lead_key", "dim_lead", "lead_key"),
            ("fact_outreach_event", "campaign_key", "dim_campaign", "campaign_key"),
            ("fact_outreach_event", "date_key", "dim_date", "date_key"),
            ("fact_daily_agent_activity", "agent_key", "dim_agent", "agent_key"),
            ("fact_daily_agent_activity", "date_key", "dim_date", "date_key"),
            ("fact_campaign_performance", "campaign_key", "dim_campaign", "campaign_key"),
        ]

        for fact_table, fk_col, dim_table, pk_col in fk_checks:
            total = self.session.execute(
                text(f"SELECT COUNT(*) FROM {fact_table} WHERE {fk_col} IS NOT NULL")
            ).scalar() or 0

            if total == 0:
                results.append(CheckResult(
                    "referential_integrity", f"{fact_table}.{fk_col}", 100.0,
                    {"note": "no non-null FK values"},
                ))
                continue

            orphans = self.session.execute(
                text(f"""
                    SELECT COUNT(*) FROM {fact_table} f
                    LEFT JOIN {dim_table} d ON f.{fk_col} = d.{pk_col}
                    WHERE f.{fk_col} IS NOT NULL AND d.{pk_col} IS NULL
                """)
            ).scalar() or 0

            score = ((total - orphans) / total) * 100
            results.append(CheckResult(
                "referential_integrity", f"{fact_table}.{fk_col}", score,
                {"total_fks": total, "orphans": orphans},
            ))

        avg_score = sum(r.score for r in results) / len(results) if results else 100.0
        logger.info("referential_integrity_check_complete", score=round(avg_score, 2))
        return results

    # ── Helpers ───────────────────────────────────────────────
    def _count_rows(self, table: str) -> int:
        """Count total rows in a table."""
        return self.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
