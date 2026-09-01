"""
Pipeline orchestrator — coordinates extraction, transformation, and loading.

Features:
- Watermark-based incremental loading
- Pipeline run metadata tracking
- Aggregation of daily agent activity and campaign performance
- DQ check integration
- End-to-end correlation ID propagation
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import DataSourceMode, settings
from src.logging_config import get_logger, set_correlation_id
from src.models import get_session, init_db
from src.models.facts import FactPipelineRun
from src.models.staging import PipelineWatermark
from src.pipeline.dead_letter import DeadLetterQueue
from src.pipeline.extractor import CSVExtractor, PolluaxAPIClient, get_extractor
from src.pipeline.loader import IdempotentLoader
from src.pipeline.transformer import DataTransformer

logger = get_logger("orchestrator")


class PipelineOrchestrator:
    """
    Orchestrates the full ETL pipeline:

    1. Check watermarks for incremental position
    2. Extract data from API or CSV
    3. Transform and validate records
    4. Load into Star Schema (idempotent upsert)
    5. Aggregate daily metrics
    6. Run data quality checks
    7. Record pipeline run metadata
    8. Flush dead-letter queue
    """

    def __init__(self, session: Session | None = None):
        self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.correlation_id = set_correlation_id()
        self.session = session or get_session()
        self.dlq = DeadLetterQueue()
        self.transformer = DataTransformer(dlq=self.dlq, run_id=self.run_id)
        self.loader = IdempotentLoader(
            session=self.session, dlq=self.dlq, run_id=self.run_id
        )
        self.start_time = datetime.now(timezone.utc)
        self.rows_extracted = 0
        self.rows_loaded = 0
        self.rows_failed = 0

    def run(self) -> dict[str, Any]:
        """
        Execute the full pipeline.

        Returns a summary dict with run metadata.
        """
        logger.info(
            "pipeline_started",
            run_id=self.run_id,
            mode=settings.data_source_mode.value,
        )

        try:
            # Ensure tables exist
            init_db()

            # Seed reference data
            self._seed_account_tiers()
            self._seed_date_dimension()

            # Extract → Transform → Load
            self._process_agents()
            self._process_leads()
            self._process_campaigns()
            self._process_templates()
            self._process_outreach_events()

            # Aggregate daily metrics
            self._aggregate_daily_agent_activity()
            self._aggregate_campaign_performance()

            # Run DQ checks
            dq_score = self._run_dq_checks()

            # Record pipeline run
            status = "SUCCESS" if self.dlq.count == 0 else "PARTIAL"
            self._record_pipeline_run(status, dq_score=dq_score)

            # Flush DLQ to database
            self.dlq.flush_to_db(self.session)

            summary = {
                "run_id": self.run_id,
                "status": status,
                "rows_extracted": self.rows_extracted,
                "rows_loaded": self.rows_loaded,
                "rows_failed": self.rows_failed,
                "dlq_count": self.dlq.count,
                "dq_score": dq_score,
                "duration_seconds": (datetime.now(timezone.utc) - self.start_time).total_seconds(),
            }

            logger.info("pipeline_completed", **summary)
            return summary

        except Exception as exc:
            logger.error("pipeline_failed", error=str(exc), run_id=self.run_id)
            try:
                self.session.rollback()
                self._record_pipeline_run("FAILED", error_message=str(exc))
                self.dlq.flush_to_db(self.session)
            except Exception as inner_exc:
                logger.error("failed_to_record_failure", error=str(inner_exc))
            raise

    def _get_watermark(self, entity_name: str) -> str | None:
        """Get the last-synced timestamp for an entity."""
        row = self.session.execute(
            text("SELECT last_synced_at FROM pipeline_watermarks WHERE entity_name = :name"),
            {"name": entity_name},
        ).fetchone()
        if row and row[0]:
            return row[0].isoformat()
        return None

    def _update_watermark(self, entity_name: str, synced_at: datetime) -> None:
        """Update the watermark for an entity after successful sync."""
        self.session.execute(
            text("""
                INSERT INTO pipeline_watermarks (entity_name, last_synced_at, updated_at)
                VALUES (:name, :synced_at, :now)
                ON CONFLICT (entity_name) DO UPDATE
                SET last_synced_at = :synced_at, updated_at = :now
            """),
            {"name": entity_name, "synced_at": synced_at, "now": datetime.now(timezone.utc)},
        )
        self.session.commit()

    def _process_agents(self) -> None:
        """Extract, transform, and load agents."""
        logger.info("processing_agents")
        since = self._get_watermark("agents")
        extractor = get_extractor()

        raw_records: list[dict] = []
        if isinstance(extractor, PolluaxAPIClient):
            for batch in extractor.fetch_agents(since=since):
                raw_records.extend(batch)
        else:
            raw_records = extractor.fetch_agents()

        self.rows_extracted += len(raw_records)

        if raw_records:
            clean = self.transformer.transform_agents(raw_records)
            result = self.loader.load_agents(clean)
            self.rows_loaded += result.inserted + result.updated
            self.rows_failed += result.failed
            self._update_watermark("agents", datetime.now(timezone.utc))

    def _process_leads(self) -> None:
        """Extract, transform, and load leads."""
        logger.info("processing_leads")
        since = self._get_watermark("leads")
        extractor = get_extractor()

        raw_records: list[dict] = []
        if isinstance(extractor, PolluaxAPIClient):
            for batch in extractor.fetch_leads(since=since):
                raw_records.extend(batch)
        else:
            raw_records = extractor.fetch_leads()

        self.rows_extracted += len(raw_records)

        if raw_records:
            clean = self.transformer.transform_leads(raw_records)
            result = self.loader.load_leads(clean)
            self.rows_loaded += result.inserted + result.updated
            self.rows_failed += result.failed
            self._update_watermark("leads", datetime.now(timezone.utc))

    def _process_campaigns(self) -> None:
        """Extract, transform, and load campaigns."""
        logger.info("processing_campaigns")
        since = self._get_watermark("campaigns")
        extractor = get_extractor()

        raw_records: list[dict] = []
        if isinstance(extractor, PolluaxAPIClient):
            for batch in extractor.fetch_campaigns(since=since):
                raw_records.extend(batch)
        else:
            raw_records = extractor.fetch_campaigns()

        self.rows_extracted += len(raw_records)

        if raw_records:
            clean = self.transformer.transform_campaigns(raw_records)
            result = self.loader.load_campaigns(clean)
            self.rows_loaded += result.inserted + result.updated
            self.rows_failed += result.failed
            self._update_watermark("campaigns", datetime.now(timezone.utc))

    def _process_templates(self) -> None:
        """Extract, transform, and load message templates."""
        logger.info("processing_templates")
        extractor = get_extractor()

        raw_records: list[dict] = []
        if isinstance(extractor, CSVExtractor):
            raw_records = extractor.fetch_message_templates()
        # API mode: templates may be embedded in campaign data — skip if no endpoint

        self.rows_extracted += len(raw_records)

        if raw_records:
            clean = self.transformer.transform_templates(raw_records)
            result = self.loader.load_templates(clean)
            self.rows_loaded += result.inserted + result.updated
            self.rows_failed += result.failed

    def _process_outreach_events(self) -> None:
        """Extract, transform, and load outreach events."""
        logger.info("processing_outreach_events")
        since = self._get_watermark("outreach_events")
        extractor = get_extractor()

        raw_records: list[dict] = []
        if isinstance(extractor, PolluaxAPIClient):
            for batch in extractor.fetch_outreach_events(since=since):
                raw_records.extend(batch)
        else:
            raw_records = extractor.fetch_outreach_events()

        self.rows_extracted += len(raw_records)

        if raw_records:
            clean = self.transformer.transform_outreach_events(raw_records)
            result = self.loader.load_outreach_events(clean)
            self.rows_loaded += result.inserted + result.updated
            self.rows_failed += result.failed
            self._update_watermark("outreach_events", datetime.now(timezone.utc))

    def _aggregate_daily_agent_activity(self) -> None:
        """
        Aggregate fact_outreach_event into fact_daily_agent_activity.

        Computes daily counts, acceptance/reply rates, and utilisation %.
        """
        logger.info("aggregating_daily_agent_activity")
        try:
            self.session.execute(text("""
                INSERT INTO fact_daily_agent_activity
                    (agent_key, date_key, invites_sent, invites_accepted,
                     messages_sent, replies_received, meetings_booked,
                     acceptance_rate, reply_rate)
                SELECT
                    e.agent_key,
                    e.date_key,
                    COUNT(*) FILTER (WHERE e.event_type = 'INVITE_SENT') AS invites_sent,
                    COUNT(*) FILTER (WHERE e.event_type = 'ACCEPTED') AS invites_accepted,
                    COUNT(*) FILTER (WHERE e.event_type = 'MESSAGE_SENT') AS messages_sent,
                    COUNT(*) FILTER (WHERE e.event_type = 'REPLY_RECEIVED') AS replies_received,
                    COUNT(*) FILTER (WHERE e.event_type = 'MEETING_BOOKED') AS meetings_booked,
                    CASE
                        WHEN COUNT(*) FILTER (WHERE e.event_type = 'INVITE_SENT') > 0
                        THEN ROUND(
                            COUNT(*) FILTER (WHERE e.event_type = 'ACCEPTED')::numeric /
                            COUNT(*) FILTER (WHERE e.event_type = 'INVITE_SENT')::numeric, 4
                        )
                        ELSE NULL
                    END AS acceptance_rate,
                    CASE
                        WHEN COUNT(*) FILTER (WHERE e.event_type = 'ACCEPTED') > 0
                        THEN ROUND(
                            COUNT(*) FILTER (WHERE e.event_type = 'REPLY_RECEIVED')::numeric /
                            COUNT(*) FILTER (WHERE e.event_type = 'ACCEPTED')::numeric, 4
                        )
                        ELSE NULL
                    END AS reply_rate
                FROM fact_outreach_event e
                WHERE e.agent_key IS NOT NULL AND e.date_key IS NOT NULL
                GROUP BY e.agent_key, e.date_key
                ON CONFLICT (agent_key, date_key) DO UPDATE SET
                    invites_sent = EXCLUDED.invites_sent,
                    invites_accepted = EXCLUDED.invites_accepted,
                    messages_sent = EXCLUDED.messages_sent,
                    replies_received = EXCLUDED.replies_received,
                    meetings_booked = EXCLUDED.meetings_booked,
                    acceptance_rate = EXCLUDED.acceptance_rate,
                    reply_rate = EXCLUDED.reply_rate
            """))
            self.session.commit()
            logger.info("daily_agent_activity_aggregated")
        except Exception as exc:
            self.session.rollback()
            logger.error("aggregation_failed", target="daily_agent_activity", error=str(exc))

    def _aggregate_campaign_performance(self) -> None:
        """Aggregate fact_outreach_event into fact_campaign_performance."""
        logger.info("aggregating_campaign_performance")
        try:
            self.session.execute(text("""
                INSERT INTO fact_campaign_performance
                    (campaign_key, date_key, total_leads, invites_sent, connected,
                     replied, meetings_booked, conversion_rate)
                SELECT
                    e.campaign_key,
                    e.date_key,
                    COUNT(DISTINCT e.lead_key) AS total_leads,
                    COUNT(*) FILTER (WHERE e.event_type = 'INVITE_SENT') AS invites_sent,
                    COUNT(*) FILTER (WHERE e.event_type = 'ACCEPTED') AS connected,
                    COUNT(*) FILTER (WHERE e.event_type = 'REPLY_RECEIVED') AS replied,
                    COUNT(*) FILTER (WHERE e.event_type = 'MEETING_BOOKED') AS meetings_booked,
                    CASE
                        WHEN COUNT(*) FILTER (WHERE e.event_type = 'INVITE_SENT') > 0
                        THEN ROUND(
                            COUNT(*) FILTER (WHERE e.event_type = 'MEETING_BOOKED')::numeric /
                            COUNT(*) FILTER (WHERE e.event_type = 'INVITE_SENT')::numeric, 4
                        )
                        ELSE NULL
                    END AS conversion_rate
                FROM fact_outreach_event e
                WHERE e.campaign_key IS NOT NULL AND e.date_key IS NOT NULL
                GROUP BY e.campaign_key, e.date_key
                ON CONFLICT (campaign_key, date_key) DO UPDATE SET
                    total_leads = EXCLUDED.total_leads,
                    invites_sent = EXCLUDED.invites_sent,
                    connected = EXCLUDED.connected,
                    replied = EXCLUDED.replied,
                    meetings_booked = EXCLUDED.meetings_booked,
                    conversion_rate = EXCLUDED.conversion_rate
            """))
            self.session.commit()
            logger.info("campaign_performance_aggregated")
        except Exception as exc:
            self.session.rollback()
            logger.error("aggregation_failed", target="campaign_performance", error=str(exc))

    def _run_dq_checks(self) -> float | None:
        """Run data quality checks and return composite score."""
        try:
            from src.quality.scoring import DQScorer
            scorer = DQScorer(session=self.session, run_id=self.run_id)
            score = scorer.run_all_checks()
            return score
        except ImportError:
            logger.warning("dq_module_not_available")
            return None
        except Exception as exc:
            logger.error("dq_checks_failed", error=str(exc))
            return None

    def _record_pipeline_run(
        self,
        status: str,
        dq_score: float | None = None,
        error_message: str | None = None,
    ) -> None:
        """Persist pipeline run metadata to fact_pipeline_run."""
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.start_time).total_seconds()

        run = FactPipelineRun(
            run_id=self.run_id,
            correlation_id=self.correlation_id,
            start_time=self.start_time,
            end_time=end_time,
            duration_seconds=duration,
            rows_extracted=self.rows_extracted,
            rows_loaded=self.rows_loaded,
            rows_failed=self.rows_failed,
            rows_skipped=0,
            status=status,
            error_message=error_message,
            dq_score=dq_score,
            dq_passed=(dq_score or 0) >= settings.dq_pass_threshold if dq_score else None,
        )
        self.session.add(run)
        self.session.commit()
        logger.info(
            "pipeline_run_recorded",
            run_id=self.run_id,
            status=status,
            duration_seconds=round(duration, 2),
        )

    def _seed_account_tiers(self) -> None:
        """Seed dim_account_tier with the Polluxa rate-limit matrix."""
        tiers = [
            ("< 1 Month", "Very High Risk", 5, 10),
            ("1 Month", "High Risk", 10, 15),
            ("2-6 Months", "Moderate Risk", 15, 25),
            ("6-12 Months", "Low Risk", 25, 40),
            ("1+ Year", "Minimal Risk", 30, 60),
        ]
        for name, risk, invites, messages in tiers:
            self.session.execute(
                text("""
                    INSERT INTO dim_account_tier (tier_name, risk_classification, daily_invite_limit, daily_message_limit)
                    VALUES (:name, :risk, :invites, :messages)
                    ON CONFLICT (tier_name) DO NOTHING
                """),
                {"name": name, "risk": risk, "invites": invites, "messages": messages},
            )
        self.session.commit()

    def _seed_date_dimension(self) -> None:
        """Populate dim_date with dates for the analysis period."""
        # Check if already populated
        count = self.session.execute(text("SELECT COUNT(*) FROM dim_date")).scalar()
        if count and count > 0:
            return

        start = date(2024, 1, 1)
        end = date(2027, 12, 31)
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        month_names = ["", "January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]

        current = start
        while current <= end:
            self.session.execute(
                text("""
                    INSERT INTO dim_date (date_key, full_date, year, quarter, month, month_name,
                                         week_of_year, day_of_week, day_name, is_weekend)
                    VALUES (:dk, :fd, :y, :q, :m, :mn, :w, :dow, :dn, :iw)
                    ON CONFLICT (date_key) DO NOTHING
                """),
                {
                    "dk": int(current.strftime("%Y%m%d")),
                    "fd": current,
                    "y": current.year,
                    "q": (current.month - 1) // 3 + 1,
                    "m": current.month,
                    "mn": month_names[current.month],
                    "w": current.isocalendar()[1],
                    "dow": current.weekday(),
                    "dn": day_names[current.weekday()],
                    "iw": current.weekday() >= 5,
                },
            )
            current += timedelta(days=1)

        self.session.commit()
        logger.info("date_dimension_seeded", start=str(start), end=str(end))
