"""Tests for FastAPI real-time event ingestion and webhook endpoints."""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["database"] == "CONNECTED"


def test_metrics_summary_endpoint():
    response = client.get("/api/v1/metrics/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_invites_sent" in data
    assert "acceptance_rate_pct" in data


def test_ingest_live_event():
    payload = {
        "event_id": "test_live_evt_999",
        "agent_id": "agent_001",
        "event_type": "INVITE_SENT",
        "status": "SUCCESS",
    }
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["event_type"] == "INVITE_SENT"


def test_ingest_bad_event_dlq_routing():
    bad_payload = {
        "event_id": "test_bad_evt_001",
        "agent_id": "agent_001",
        "event_type": "UNKNOWN_ACTION",
        "timestamp": "invalid-timestamp",
    }
    response = client.post("/api/v1/events", json=bad_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "DEAD_LETTERED"
