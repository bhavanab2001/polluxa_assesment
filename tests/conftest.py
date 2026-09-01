"""
Test fixtures and shared configuration for the test suite.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use a test database (SQLite in-memory for fast CI, or test Postgres)
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite:///test_polluxa.db",
)


@pytest.fixture(scope="session")
def engine():
    """Create a test database engine."""
    eng = create_engine(TEST_DB_URL, echo=False)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def create_tables(engine):
    """Create all tables in the test database."""
    # Import all models to register them
    import src.models.dimensions
    import src.models.facts
    import src.models.staging  # noqa: F401
    from src.models import Base

    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def session(engine, create_tables):
    """Create a new database session for a test."""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def sample_raw_events():
    """Sample raw outreach event data."""
    return [
        {
            "id": "evt_001",
            "agent_id": "agent_001",
            "lead_id": "lead_001",
            "campaign_id": "camp_001",
            "event_type": "INVITE_SENT",
            "timestamp": "2026-08-15T10:30:00Z",
            "status": "SUCCESS",
        },
        {
            "id": "evt_002",
            "agent_id": "agent_001",
            "lead_id": "lead_001",
            "campaign_id": "camp_001",
            "event_type": "accepted",  # Needs normalization
            "timestamp": "2026-08-16T14:00:00Z",
            "status": "SUCCESS",
        },
        {
            "id": "evt_003",
            "agent_id": "agent_001",
            "lead_id": "lead_002",
            "campaign_id": "camp_001",
            "event_type": "REPLY_RECEIVED",
            "timestamp": "2026-08-17T09:15:00Z",
            "status": "SUCCESS",
            "response_time_minutes": 120,
        },
    ]


@pytest.fixture
def sample_raw_agents():
    """Sample raw agent data."""
    return [
        {
            "id": "agent_001",
            "name": "Test Agent Alpha",
            "email": "alpha@test.com",
            "status": "active",
            "account_age": "6-12 Months",
        },
        {
            "id": "agent_002",
            "name": "Test Agent Beta",
            "email": "beta@test.com",
            "status": "paused",
            "account_age": "2-6 Months",
        },
    ]


@pytest.fixture
def sample_bad_events():
    """Sample events with deliberate data quality issues."""
    return [
        {"id": None, "event_type": "INVITE_SENT", "timestamp": "2026-08-15T10:00:00Z"},  # Missing ID
        {"id": "evt_bad_1", "event_type": None, "timestamp": "2026-08-15T10:00:00Z"},  # Missing type
        {"id": "evt_bad_2", "event_type": "INVITE_SENT", "timestamp": "not-a-date"},  # Bad timestamp
        {"id": "evt_bad_3", "event_type": "INVITE_SENT", "timestamp": ""},  # Empty timestamp
    ]
