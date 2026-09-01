"""
Idempotent data loader — upserts data into PostgreSQL.

Uses INSERT ... ON CONFLICT DO UPDATE to ensure that re-running
the pipeline never creates duplicate records. Processes in
configurable batch sizes with transaction-per-batch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import settings
from src.logging_config import get_logger
from src.pipeline.dead_letter import DeadLetterQueue

logger = get_logger("loader")


class LoadResult:
    """Tracks the outcome of a load operation."""

    def __init__(self) -> None:
        self.inserted: int = 0
        self.updated: int = 0
        self.skipped: int = 0
        self.failed: int = 0

    @property
    def total_processed(self) -> int:
        return self.inserted + self.updated + self.skipped + self.failed

    def __repr__(self) -> str:
        return (
            f"LoadResult(inserted={self.inserted}, updated={self.updated}, "
            f"skipped={self.skipped}, failed={self.failed})"
        )


class IdempotentLoader:
    """
    Loads transformed data into PostgreSQL using idempotent upserts.

    Features:
    - INSERT ... ON CONFLICT DO UPDATE for deduplication
    - Batch processing with configurable batch size
    - Transaction-per-batch with rollback on failure
    - SCD Type 2 handling for dimension tables
    """

    def __init__(
        self,
        session: Session,
        dlq: DeadLetterQueue | None = None,
        batch_size: int | None = None,
        run_id: str | None = None,
    ):
        self.session = session
        self.dlq = dlq or DeadLetterQueue()
        self.batch_size = batch_size or settings.loader_batch_size
        self.run_id = run_id

    def _execute_upsert(
        self,
        table_name: str,
        conflict_column: str,
        records: list[dict[str, Any]],
        update_columns: list[str],
    ) -> LoadResult:
        """
        Execute an idempotent upsert using INSERT ... ON CONFLICT DO UPDATE.

        Args:
            table_name: Target table name.
            conflict_column: The unique/natural key column for ON CONFLICT.
            records: List of record dicts to insert/update.
            update_columns: Columns to update on conflict.

        Returns:
            LoadResult with counts of inserted, updated, skipped, failed.
        """
        result = LoadResult()

        if not records:
            return result

        # Process in batches
        for batch_start in range(0, len(records), self.batch_size):
            batch = records[batch_start : batch_start + self.batch_size]

            try:
                for record in batch:
                    # Build column lists from the record keys
                    columns = list(record.keys())
                    placeholders = ", ".join([f":{col}" for col in columns])
                    col_list = ", ".join(columns)

                    # Build SET clause for update
                    if update_columns:
                        set_clause = ", ".join(
                            [f"{col} = EXCLUDED.{col}" for col in update_columns]
                        )
                        sql = text(f"""
                            INSERT INTO {table_name} ({col_list})
                            VALUES ({placeholders})
                            ON CONFLICT ({conflict_column}) DO UPDATE
                            SET {set_clause}
                        """)
                    else:
                        sql = text(f"""
                            INSERT INTO {table_name} ({col_list})
                            VALUES ({placeholders})
                            ON CONFLICT ({conflict_column}) DO NOTHING
                        """)

                    try:
                        db_result = self.session.execute(sql, record)
                        if db_result.rowcount > 0:
                            result.inserted += 1
                        else:
                            result.skipped += 1
                    except Exception as exc:
                        result.failed += 1
                        self.dlq.add(
                            record,
                            f"Load error: {str(exc)}",
                            "loader",
                            self.run_id,
                        )

                self.session.commit()

            except Exception as exc:
                self.session.rollback()
                logger.error(
                    "batch_load_failed",
                    table=table_name,
                    batch_start=batch_start,
                    batch_size=len(batch),
                    error=str(exc),
                )
                result.failed += len(batch)

        logger.info(
            "load_complete",
            table=table_name,
            inserted=result.inserted,
            updated=result.updated,
            skipped=result.skipped,
            failed=result.failed,
        )
        return result

    def load_agents(self, records: list[dict[str, Any]]) -> LoadResult:
        """
        Load agent records with SCD Type 2 handling.

        For agents that have changed status or tier, the current row is
        closed and a new version is inserted.
        """
        result = LoadResult()

        for record in records:
            try:
                agent_id = record["agent_id"]

                # Check if a current version exists
                existing = self.session.execute(
                    text("""
                        SELECT agent_key, status, tier_key
                        FROM dim_agent
                        WHERE agent_id = :agent_id AND is_current = true
                    """),
                    {"agent_id": agent_id},
                ).fetchone()

                new_status = record.get("status", "active")

                if existing is None:
                    # New agent — insert
                    self.session.execute(
                        text("""
                            INSERT INTO dim_agent (agent_id, linkedin_email, display_name, status, is_current, valid_from)
                            VALUES (:agent_id, :linkedin_email, :display_name, :status, true, :valid_from)
                        """),
                        {
                            **record,
                            "status": new_status,
                            "valid_from": datetime.now(timezone.utc),
                        },
                    )
                    result.inserted += 1
                elif existing[1] != new_status:
                    # Status changed — close current version, insert new
                    now = datetime.now(timezone.utc)
                    self.session.execute(
                        text("""
                            UPDATE dim_agent
                            SET is_current = false, valid_to = :valid_to
                            WHERE agent_key = :agent_key
                        """),
                        {"agent_key": existing[0], "valid_to": now},
                    )
                    self.session.execute(
                        text("""
                            INSERT INTO dim_agent (agent_id, linkedin_email, display_name, status, is_current, valid_from)
                            VALUES (:agent_id, :linkedin_email, :display_name, :status, true, :valid_from)
                        """),
                        {
                            **record,
                            "status": new_status,
                            "valid_from": now,
                        },
                    )
                    result.updated += 1
                else:
                    # No change
                    result.skipped += 1

                self.session.commit()

            except Exception as exc:
                self.session.rollback()
                result.failed += 1
                self.dlq.add(record, str(exc), "loader", self.run_id)

        logger.info("agents_loaded", **result.__dict__)
        return result

    def load_leads(self, records: list[dict[str, Any]]) -> LoadResult:
        """Load lead records with SCD Type 2 handling."""
        result = LoadResult()

        for record in records:
            try:
                lead_id = record["lead_id"]

                existing = self.session.execute(
                    text("""
                        SELECT lead_key, segment, lead_status
                        FROM dim_lead
                        WHERE lead_id = :lead_id AND is_current = true
                    """),
                    {"lead_id": lead_id},
                ).fetchone()

                new_segment = record.get("segment")
                new_status = record.get("lead_status")

                if existing is None:
                    self.session.execute(
                        text("""
                            INSERT INTO dim_lead
                            (lead_id, full_name, company, title, linkedin_url, segment, lead_status, is_current, valid_from)
                            VALUES (:lead_id, :full_name, :company, :title, :linkedin_url, :segment, :lead_status, true, :valid_from)
                        """),
                        {**record, "valid_from": datetime.now(timezone.utc)},
                    )
                    result.inserted += 1
                elif existing[1] != new_segment or existing[2] != new_status:
                    now = datetime.now(timezone.utc)
                    self.session.execute(
                        text("UPDATE dim_lead SET is_current = false, valid_to = :vt WHERE lead_key = :lk"),
                        {"lk": existing[0], "vt": now},
                    )
                    self.session.execute(
                        text("""
                            INSERT INTO dim_lead
                            (lead_id, full_name, company, title, linkedin_url, segment, lead_status, is_current, valid_from)
                            VALUES (:lead_id, :full_name, :company, :title, :linkedin_url, :segment, :lead_status, true, :valid_from)
                        """),
                        {**record, "valid_from": now},
                    )
                    result.updated += 1
                else:
                    result.skipped += 1

                self.session.commit()

            except Exception as exc:
                self.session.rollback()
                result.failed += 1
                self.dlq.add(record, str(exc), "loader", self.run_id)

        logger.info("leads_loaded", **result.__dict__)
        return result

    def load_campaigns(self, records: list[dict[str, Any]]) -> LoadResult:
        """Load campaign records (SCD Type 1 — upsert)."""
        return self._execute_upsert(
            "dim_campaign",
            "campaign_id",
            records,
            ["campaign_name", "campaign_type", "target_segment"],
        )

    def load_templates(self, records: list[dict[str, Any]]) -> LoadResult:
        """Load message template records (SCD Type 1 — upsert)."""
        return self._execute_upsert(
            "dim_message_template",
            "template_id",
            records,
            ["template_name", "template_body", "channel"],
        )

    def load_outreach_events(self, records: list[dict[str, Any]]) -> LoadResult:
        """
        Load outreach events into fact_outreach_event.

        Resolves dimension keys (agent_key, lead_key, campaign_key)
        by looking up current dimension records.
        """
        result = LoadResult()

        for batch_start in range(0, len(records), self.batch_size):
            batch = records[batch_start : batch_start + self.batch_size]

            try:
                for record in batch:
                    try:
                        # Resolve dimension keys
                        agent_key = self._resolve_dimension_key(
                            "dim_agent", "agent_key", "agent_id",
                            record.get("agent_id"), scd2=True
                        )
                        lead_key = self._resolve_dimension_key(
                            "dim_lead", "lead_key", "lead_id",
                            record.get("lead_id"), scd2=True
                        )
                        campaign_key = self._resolve_dimension_key(
                            "dim_campaign", "campaign_key", "campaign_id",
                            record.get("campaign_id")
                        )
                        template_key = self._resolve_dimension_key(
                            "dim_message_template", "template_key", "template_id",
                            record.get("template_id")
                        )

                        db_result = self.session.execute(
                            text("""
                                INSERT INTO fact_outreach_event
                                (event_source_id, agent_key, lead_key, campaign_key, date_key,
                                 template_key, event_type, event_timestamp, event_status, response_time_minutes)
                                VALUES
                                (:event_source_id, :agent_key, :lead_key, :campaign_key, :date_key,
                                 :template_key, :event_type, :event_timestamp, :event_status, :response_time_minutes)
                                ON CONFLICT (event_source_id) DO UPDATE SET
                                    event_status = EXCLUDED.event_status,
                                    response_time_minutes = EXCLUDED.response_time_minutes
                            """),
                            {
                                "event_source_id": record["event_source_id"],
                                "agent_key": agent_key,
                                "lead_key": lead_key,
                                "campaign_key": campaign_key,
                                "date_key": record.get("date_key"),
                                "template_key": template_key,
                                "event_type": record["event_type"],
                                "event_timestamp": record["event_timestamp"],
                                "event_status": record.get("event_status", "SUCCESS"),
                                "response_time_minutes": record.get("response_time_minutes"),
                            },
                        )
                        if db_result.rowcount > 0:
                            result.inserted += 1
                        else:
                            result.skipped += 1

                    except Exception as exc:
                        result.failed += 1
                        self.dlq.add(record, str(exc), "loader", self.run_id)

                self.session.commit()

            except Exception as exc:
                self.session.rollback()
                result.failed += len(batch)
                logger.error("event_batch_failed", error=str(exc))

        logger.info("events_loaded", **result.__dict__)
        return result

    def _resolve_dimension_key(
        self,
        table: str,
        key_column: str,
        id_column: str,
        id_value: str | None,
        scd2: bool = False,
    ) -> int | None:
        """Look up a dimension surrogate key by natural key."""
        if not id_value:
            return None
        where = f"{id_column} = :id_val"
        if scd2:
            where += " AND is_current = true"
        row = self.session.execute(
            text(f"SELECT {key_column} FROM {table} WHERE {where} LIMIT 1"),
            {"id_val": id_value},
        ).fetchone()
        return row[0] if row else None


# Backward compatibility alias
DataLoader = IdempotentLoader
