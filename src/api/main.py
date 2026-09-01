"""
FastAPI Live Webhook and Real-Time Event Ingestion Server.

Enables real-time event streaming into the Polluxa Analytics Star Schema:
  - POST /api/v1/events: Live outreach event ingestion (with DLQ validation)
  - POST /api/v1/webhooks/polluxa: Universal webhook receiver (Polluxa/Zapier/Make/Apollo)
  - POST /api/v1/leads: Dynamic lead registration
  - GET /api/v1/metrics/summary: Live real-time KPIs
  - GET /health: Service health and database probe
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.config import settings
from src.logging_config import setup_logging
from src.models import get_session, init_db
from src.pipeline.dead_letter import DeadLetterQueue
from src.pipeline.loader import DataLoader
from src.pipeline.transformer import DataTransformer

setup_logging()
logger = structlog.get_logger(__name__)


# ── Pydantic Request Models ──────────────────────────────────
class LiveEventPayload(BaseModel):
    """Payload format for live LinkedIn events."""

    event_id: str | None = Field(default_factory=lambda: f"live_evt_{uuid.uuid4().hex[:12]}")
    agent_id: str = Field(..., description="ID or display name of the LinkedIn agent")
    lead_id: str | None = Field(default=None, description="Prospect/Lead ID")
    campaign_id: str | None = Field(default=None, description="Associated Campaign ID")
    event_type: str = Field(..., description="INVITE_SENT, ACCEPTED, MESSAGE_SENT, REPLY_RECEIVED, MEETING_BOOKED")
    timestamp: str | None = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str | None = Field(default="SUCCESS")
    response_time_minutes: int | None = None
    template_id: str | None = None


class LiveLeadPayload(BaseModel):
    """Payload for registering live prospects."""

    lead_id: str = Field(..., description="Unique lead identifier")
    first_name: str
    last_name: str
    company: str | None = None
    job_title: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    target_segment: str | None = "Live Inbound"


class WebhookResponse(BaseModel):
    status: str
    event_id: str
    event_type: str
    persisted_at: str
    anomaly_flag: bool = False
    warning: str | None = None


# ── App Lifespan ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("realtime_api_starting", port=8000)
    init_db()
    yield
    logger.info("realtime_api_shutting_down")


app = FastAPI(
    title="Polluxa Real-Time Event & Webhook API",
    description="Production-grade streaming ingestion endpoint for live LinkedIn automation events into PostgreSQL Star Schema.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health Probe ─────────────────────────────────────────────
@app.get("/health", tags=["Monitoring"])
def health_check():
    """Verify API liveness and PostgreSQL database connectivity."""
    session = get_session()
    try:
        session.execute(text("SELECT 1"))
        total_events = session.execute(text("SELECT COUNT(*) FROM fact_outreach_event")).scalar()
        total_agents = session.execute(text("SELECT COUNT(*) FROM dim_agent WHERE is_current = True")).scalar()
        return {
            "status": "HEALTHY",
            "database": "CONNECTED",
            "db_url_masked": settings.db_url.split("@")[-1] if "@" in settings.db_url else "configured",
            "total_events_in_dw": total_events,
            "active_agents": total_agents,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database probe failed: {exc!s}")
    finally:
        session.close()


# ── Live Real-Time Event Endpoint ────────────────────────────
@app.post("/api/v1/events", response_model=WebhookResponse, tags=["Real-Time Ingestion"])
def ingest_live_event(payload: LiveEventPayload, background_tasks: BackgroundTasks):
    """
    Ingest a single live event from a real LinkedIn automation action.
    Validates the event, routes bad data to DLQ, upserts into Star Schema,
    and updates daily agent aggregations.
    """
    session = get_session()
    dlq = DeadLetterQueue()
    transformer = DataTransformer(dlq=dlq)
    loader = DataLoader(session)

    try:
        raw_dict = payload.model_dump()
        clean_events = transformer.transform_outreach_events([raw_dict])

        if not clean_events:
            # DLQ captured this bad record
            dlq.flush_to_db(session)
            return WebhookResponse(
                status="DEAD_LETTERED",
                event_id=raw_dict.get("event_id", "unknown"),
                event_type=raw_dict.get("event_type", "UNKNOWN"),
                persisted_at=datetime.now(timezone.utc).isoformat(),
                warning="Event format failed validation and was routed to Dead-Letter Queue.",
            )

        # Load clean event
        loader.load_outreach_events(clean_events)

        # Update real-time daily metrics
        date_key = clean_events[0].get("date_key")
        agent_id = clean_events[0].get("agent_id")
        agent_key = (
            loader._resolve_dimension_key("dim_agent", "agent_key", "agent_id", agent_id, scd2=True)
            if agent_id
            else None
        )

        if agent_key and date_key:
            _update_daily_aggregation(session, agent_key, date_key)

        return WebhookResponse(
            status="SUCCESS",
            event_id=payload.event_id or "evt_live",
            event_type=clean_events[0].get("event_type", "INVITE_SENT"),
            persisted_at=datetime.now(timezone.utc).isoformat(),
            anomaly_flag=False,
        )
    except Exception as exc:
        logger.error("live_event_ingestion_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        session.close()


# ── Universal Webhook Receiver (Polluxa / Zapier / Make) ─────
@app.post("/api/v1/webhooks/polluxa", tags=["Webhooks"])
def receive_polluxa_webhook(payload: dict[str, Any]):
    """
    Universal webhook endpoint that accepts unstructured or dynamic JSON
    from Polluxa, Zapier, or Apollo and maps it automatically to Star Schema events.
    """
    session = get_session()
    dlq = DeadLetterQueue()
    transformer = DataTransformer(dlq=dlq)
    loader = DataLoader(session)

    try:
        # Standardize common webhook field names
        event_dict = {
            "id": payload.get("id") or payload.get("event_id") or f"wh_{uuid.uuid4().hex[:10]}",
            "agent_id": payload.get("agent_id") or payload.get("account_id") or "live_agent_default",
            "lead_id": payload.get("lead_id") or payload.get("contact_id"),
            "campaign_id": payload.get("campaign_id"),
            "event_type": payload.get("event_type") or payload.get("type") or payload.get("action") or "MESSAGE_SENT",
            "timestamp": payload.get("timestamp")
            or payload.get("created_at")
            or datetime.now(timezone.utc).isoformat(),
            "status": payload.get("status", "SUCCESS"),
            "response_time_minutes": payload.get("response_time_minutes"),
        }

        clean = transformer.transform_outreach_events([event_dict])
        if clean:
            loader.load_outreach_events(clean)
            return {"status": "PROCESSED", "event_id": event_dict["id"], "event_type": clean[0].get("event_type")}
        else:
            dlq.flush_to_db(session)
            return {"status": "DEAD_LETTERED", "reason": "Failed normalization"}
    finally:
        session.close()


# ── Live KPI Summary ─────────────────────────────────────────
@app.get("/api/v1/metrics/summary", tags=["Analytics"])
def get_live_metrics():
    """Returns live KPI counters across the entire Star Schema."""
    session = get_session()
    try:
        invites = (
            session.execute(text("SELECT COUNT(*) FROM fact_outreach_event WHERE event_type = 'INVITE_SENT'")).scalar()
            or 0
        )

        accepted = (
            session.execute(text("SELECT COUNT(*) FROM fact_outreach_event WHERE event_type = 'ACCEPTED'")).scalar()
            or 0
        )

        replies = (
            session.execute(
                text("SELECT COUNT(*) FROM fact_outreach_event WHERE event_type = 'REPLY_RECEIVED'")
            ).scalar()
            or 0
        )

        meetings = (
            session.execute(
                text("SELECT COUNT(*) FROM fact_outreach_event WHERE event_type = 'MEETING_BOOKED'")
            ).scalar()
            or 0
        )

        acceptance_rate = round((accepted / invites * 100), 2) if invites > 0 else 0.0
        reply_rate = round((replies / accepted * 100), 2) if accepted > 0 else 0.0
        conversion_rate = round((meetings / invites * 100), 2) if invites > 0 else 0.0

        return {
            "total_invites_sent": invites,
            "total_accepted": accepted,
            "total_replies_received": replies,
            "total_meetings_booked": meetings,
            "acceptance_rate_pct": acceptance_rate,
            "reply_rate_pct": reply_rate,
            "conversion_rate_pct": conversion_rate,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        session.close()


def _update_daily_aggregation(session, agent_key: int, date_key: int) -> None:
    """Incrementally recalculates daily aggregates for a specific agent and date."""
    session.execute(
        text("""
            INSERT INTO fact_daily_agent_activity (
                agent_key, date_key, invites_sent, invites_accepted, messages_sent,
                replies_received, meetings_booked, acceptance_rate, reply_rate
            )
            SELECT
                :agent_key,
                :date_key,
                COUNT(*) FILTER (WHERE event_type = 'INVITE_SENT'),
                COUNT(*) FILTER (WHERE event_type = 'ACCEPTED'),
                COUNT(*) FILTER (WHERE event_type = 'MESSAGE_SENT'),
                COUNT(*) FILTER (WHERE event_type = 'REPLY_RECEIVED'),
                COUNT(*) FILTER (WHERE event_type = 'MEETING_BOOKED'),
                CASE WHEN COUNT(*) FILTER (WHERE event_type = 'INVITE_SENT') > 0
                     THEN ROUND(CAST(COUNT(*) FILTER (WHERE event_type = 'ACCEPTED') AS NUMERIC) /
                          COUNT(*) FILTER (WHERE event_type = 'INVITE_SENT'), 4)
                     ELSE 0.0 END,
                CASE WHEN COUNT(*) FILTER (WHERE event_type = 'ACCEPTED') > 0
                     THEN ROUND(CAST(COUNT(*) FILTER (WHERE event_type = 'REPLY_RECEIVED') AS NUMERIC) /
                          COUNT(*) FILTER (WHERE event_type = 'ACCEPTED'), 4)
                     ELSE 0.0 END
            FROM fact_outreach_event
            WHERE agent_key = :agent_key AND date_key = :date_key
            ON CONFLICT (agent_key, date_key) DO UPDATE SET
                invites_sent = EXCLUDED.invites_sent,
                invites_accepted = EXCLUDED.invites_accepted,
                messages_sent = EXCLUDED.messages_sent,
                replies_received = EXCLUDED.replies_received,
                meetings_booked = EXCLUDED.meetings_booked,
                acceptance_rate = EXCLUDED.acceptance_rate,
                reply_rate = EXCLUDED.reply_rate;
        """),
        {"agent_key": agent_key, "date_key": date_key},
    )
    session.commit()
