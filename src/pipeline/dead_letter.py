"""
Dead-letter queue for capturing failed records.

Records that fail validation, transformation, or loading are captured
here instead of being silently dropped. This enables:
- Manual review and debugging
- Replay of corrected records
- Auditability of data loss
"""

from __future__ import annotations

from typing import Any

from src.logging_config import get_logger

logger = get_logger("dead_letter")


class DeadLetterQueue:
    """
    In-memory dead-letter queue that collects failed records
    during a pipeline run. Flushed to the database at the end.
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    @property
    def count(self) -> int:
        """Number of records in the DLQ."""
        return len(self._records)

    @property
    def records(self) -> list[dict[str, Any]]:
        """All records captured in the DLQ."""
        return list(self._records)

    def add(
        self,
        record: dict[str, Any],
        error_message: str,
        source: str,
        run_id: str | None = None,
    ) -> None:
        """
        Add a failed record to the dead-letter queue.

        Args:
            record: The original record payload that failed.
            error_message: Description of why the record failed.
            source: Pipeline stage where the failure occurred
                    (extractor, transformer, loader, dq_check).
            run_id: The current pipeline run ID for traceability.
        """
        entry = {
            "source_id": str(record.get("id", record.get("event_id", "unknown"))),
            "record_payload": record,
            "error_message": error_message,
            "error_type": type(error_message).__name__ if isinstance(error_message, Exception) else "ValidationError",
            "source": source,
            "run_id": run_id,
        }
        self._records.append(entry)
        logger.warning(
            "record_dead_lettered",
            source_id=entry["source_id"],
            error=error_message,
            source_stage=source,
        )

    def flush_to_db(self, session: Any) -> int:
        """
        Persist all DLQ records to the dead_letter_queue table.

        Returns the number of records flushed.
        """
        if not self._records:
            return 0

        from src.models.staging import DeadLetterRecord

        count = 0
        for entry in self._records:
            dlr = DeadLetterRecord(
                source_id=entry.get("source_id"),
                record_payload=entry["record_payload"],
                error_message=entry["error_message"],
                error_type=entry.get("error_type"),
                source=entry.get("source"),
                run_id=entry.get("run_id"),
            )
            session.add(dlr)
            count += 1

        session.commit()
        logger.info("dlq_flushed_to_db", record_count=count)
        self._records.clear()
        return count

    def clear(self) -> None:
        """Clear all records from the in-memory queue."""
        self._records.clear()
