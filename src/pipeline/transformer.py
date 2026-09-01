"""
Data transformer — cleaning, normalization, and type casting.

Transforms raw API/CSV data into clean records ready for loading
into the Star Schema. Handles:
- Timestamp normalization to UTC
- Null handling and type coercion
- Event type enum mapping
- Deduplication by natural key
- Validation and dead-letter routing for bad records
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.logging_config import get_logger
from src.pipeline.dead_letter import DeadLetterQueue

logger = get_logger("transformer")

# Valid event types in the system
VALID_EVENT_TYPES = {
    "INVITE_SENT",
    "ACCEPTED",
    "MESSAGE_SENT",
    "REPLY_RECEIVED",
    "MEETING_BOOKED",
    "WITHDRAWN",
    "FAILED",
}

# Mapping of common source event names to standardized types
EVENT_TYPE_MAP: dict[str, str] = {
    "invite_sent": "INVITE_SENT",
    "invitation_sent": "INVITE_SENT",
    "sent": "INVITE_SENT",
    "accepted": "ACCEPTED",
    "connected": "ACCEPTED",
    "connection_accepted": "ACCEPTED",
    "message_sent": "MESSAGE_SENT",
    "message": "MESSAGE_SENT",
    "reply_received": "REPLY_RECEIVED",
    "replied": "REPLY_RECEIVED",
    "reply": "REPLY_RECEIVED",
    "meeting_booked": "MEETING_BOOKED",
    "meeting": "MEETING_BOOKED",
    "withdrawn": "WITHDRAWN",
    "failed": "FAILED",
    "error": "FAILED",
}


def _parse_timestamp(value: Any) -> datetime | None:
    """
    Parse a timestamp value into a timezone-aware datetime (UTC).

    Handles ISO format strings, Unix timestamps, and None.
    """
    if value is None or value == "" or value == "null":
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        # Unix timestamp
        return datetime.fromtimestamp(value, tz=timezone.utc)

    if isinstance(value, str):
        # Try common ISO formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                continue

    logger.warning("unparseable_timestamp", value=str(value))
    return None


def _normalize_event_type(raw_type: str | None) -> str | None:
    """Map raw event type strings to standardized enum values."""
    if not raw_type:
        return None
    normalized = raw_type.strip().lower().replace(" ", "_").replace("-", "_")
    mapped = EVENT_TYPE_MAP.get(normalized)
    if mapped:
        return mapped
    upper = raw_type.strip().upper()
    if upper in VALID_EVENT_TYPES:
        return upper
    logger.warning("unknown_event_type", raw_type=raw_type)
    return raw_type.strip().upper()


def _safe_int(value: Any) -> int | None:
    """Safely convert a value to int, returning None on failure."""
    if value is None or value == "" or value == "null":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None or value == "" or value == "null":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_str(value: Any, max_length: int | None = None) -> str | None:
    """Safely convert a value to string, with optional truncation."""
    if value is None or value == "null":
        return None
    result = str(value).strip()
    if not result:
        return None
    if max_length and len(result) > max_length:
        result = result[:max_length]
    return result


def _compute_date_key(dt: datetime | None) -> int | None:
    """Convert a datetime to a YYYYMMDD integer for dim_date FK."""
    if dt is None:
        return None
    return int(dt.strftime("%Y%m%d"))


class DataTransformer:
    """
    Transforms raw records into clean, typed records ready for loading.

    Invalid records are routed to the dead-letter queue instead of
    being silently dropped.
    """

    def __init__(self, dlq: DeadLetterQueue | None = None, run_id: str | None = None):
        self.dlq = dlq or DeadLetterQueue()
        self.run_id = run_id
        self._seen_ids: set[str] = set()  # For deduplication

    def transform_agents(self, raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transform raw agent records into clean dimension records."""
        clean: list[dict[str, Any]] = []
        for record in raw_records:
            try:
                agent_id = _safe_str(record.get("id") or record.get("agent_id"))
                if not agent_id:
                    self.dlq.add(record, "Missing agent_id", "transformer", self.run_id)
                    continue
                if agent_id in self._seen_ids:
                    continue
                self._seen_ids.add(agent_id)

                clean.append({
                    "agent_id": agent_id,
                    "linkedin_email": _safe_str(record.get("email") or record.get("linkedin_email"), 255),
                    "display_name": _safe_str(record.get("name") or record.get("display_name"), 255),
                    "status": _safe_str(record.get("status"), 50) or "active",
                    "tier_name": _safe_str(record.get("account_age") or record.get("tier")),
                })
            except Exception as exc:
                self.dlq.add(record, str(exc), "transformer", self.run_id)
        logger.info("agents_transformed", input=len(raw_records), output=len(clean))
        return clean

    def transform_leads(self, raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transform raw lead records into clean dimension records."""
        import hashlib
        clean: list[dict[str, Any]] = []
        self._seen_ids.clear()
        for record in raw_records:
            try:
                lead_id = _safe_str(record.get("id") or record.get("lead_id"))
                if not lead_id:
                    # Generate deterministic natural key from url or names
                    ident = (
                        record.get("linkedin_url")
                        or record.get("Profile URL")
                        or record.get("URL")
                        or f"{record.get('first_name', '')}_{record.get('last_name', '')}"
                    )
                    if ident and ident.strip():
                        lead_id = f"lead_{hashlib.md5(ident.strip().encode()).hexdigest()[:10]}"
                    else:
                        self.dlq.add(record, "Missing lead_id", "transformer", self.run_id)
                        continue

                if lead_id in self._seen_ids:
                    continue
                self._seen_ids.add(lead_id)

                # Resolve full name
                full_name = _safe_str(record.get("name") or record.get("full_name"), 255)
                if not full_name and (record.get("first_name") or record.get("last_name")):
                    full_name = f"{record.get('first_name', '')} {record.get('last_name', '')}".strip()

                clean.append({
                    "lead_id": lead_id,
                    "full_name": full_name or "Unknown Prospect",
                    "company": _safe_str(record.get("company") or record.get("organization"), 255) or "Unknown Company",
                    "title": _safe_str(record.get("title") or record.get("job_title") or record.get("Position"), 255) or "Professional",
                    "linkedin_url": _safe_str(record.get("linkedin_url") or record.get("profile_url") or record.get("URL"), 500),
                    "segment": _safe_str(record.get("segment") or record.get("list_name") or record.get("location"), 100) or "Target Prospects",
                    "lead_status": _safe_str(record.get("status") or record.get("lead_status"), 50) or "NEW",
                })
            except Exception as exc:
                self.dlq.add(record, str(exc), "transformer", self.run_id)
        logger.info("leads_transformed", input=len(raw_records), output=len(clean))
        return clean

    def transform_campaigns(self, raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transform raw campaign records."""
        clean: list[dict[str, Any]] = []
        self._seen_ids.clear()
        for record in raw_records:
            try:
                campaign_id = _safe_str(record.get("id") or record.get("campaign_id"))
                if not campaign_id:
                    self.dlq.add(record, "Missing campaign_id", "transformer", self.run_id)
                    continue
                if campaign_id in self._seen_ids:
                    continue
                self._seen_ids.add(campaign_id)

                clean.append({
                    "campaign_id": campaign_id,
                    "campaign_name": _safe_str(record.get("name") or record.get("campaign_name"), 255),
                    "campaign_type": _safe_str(record.get("type") or record.get("campaign_type"), 100),
                    "target_segment": _safe_str(record.get("segment") or record.get("target_segment"), 100),
                    "created_at": _parse_timestamp(record.get("created_at")),
                })
            except Exception as exc:
                self.dlq.add(record, str(exc), "transformer", self.run_id)
        logger.info("campaigns_transformed", input=len(raw_records), output=len(clean))
        return clean

    def transform_outreach_events(self, raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transform raw outreach events into fact-ready records."""
        clean: list[dict[str, Any]] = []
        self._seen_ids.clear()
        for record in raw_records:
            try:
                event_source_id = _safe_str(record.get("id") or record.get("event_id"))
                if not event_source_id:
                    self.dlq.add(record, "Missing event_id", "transformer", self.run_id)
                    continue
                if event_source_id in self._seen_ids:
                    continue
                self._seen_ids.add(event_source_id)

                event_type = _normalize_event_type(
                    record.get("event_type") or record.get("type") or record.get("action")
                )
                if not event_type:
                    self.dlq.add(record, "Missing event_type", "transformer", self.run_id)
                    continue

                event_timestamp = _parse_timestamp(
                    record.get("timestamp") or record.get("event_timestamp")
                    or record.get("created_at") or record.get("date")
                )
                if not event_timestamp:
                    self.dlq.add(record, "Missing or unparseable timestamp", "transformer", self.run_id)
                    continue

                clean.append({
                    "event_source_id": event_source_id,
                    "agent_id": _safe_str(record.get("agent_id")),
                    "lead_id": _safe_str(record.get("lead_id")),
                    "campaign_id": _safe_str(record.get("campaign_id")),
                    "template_id": _safe_str(record.get("template_id")),
                    "event_type": event_type,
                    "event_timestamp": event_timestamp,
                    "date_key": _compute_date_key(event_timestamp),
                    "event_status": _safe_str(record.get("status"), 50) or "SUCCESS",
                    "response_time_minutes": _safe_int(record.get("response_time_minutes")),
                })
            except Exception as exc:
                self.dlq.add(record, str(exc), "transformer", self.run_id)

        logger.info(
            "events_transformed",
            input=len(raw_records),
            output=len(clean),
            dlq_count=self.dlq.count,
        )
        return clean

    def transform_templates(self, raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Transform raw message template records."""
        clean: list[dict[str, Any]] = []
        self._seen_ids.clear()
        for record in raw_records:
            try:
                template_id = _safe_str(record.get("id") or record.get("template_id"))
                if not template_id:
                    self.dlq.add(record, "Missing template_id", "transformer", self.run_id)
                    continue
                if template_id in self._seen_ids:
                    continue
                self._seen_ids.add(template_id)

                clean.append({
                    "template_id": template_id,
                    "template_name": _safe_str(record.get("name") or record.get("template_name"), 255),
                    "template_body": _safe_str(record.get("body") or record.get("template_body")),
                    "channel": _safe_str(record.get("channel"), 50),
                    "created_at": _parse_timestamp(record.get("created_at")),
                })
            except Exception as exc:
                self.dlq.add(record, str(exc), "transformer", self.run_id)
        logger.info("templates_transformed", input=len(raw_records), output=len(clean))
        return clean
