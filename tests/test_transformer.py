"""Tests for data transformer and normalization."""

import pytest
from src.pipeline.dead_letter import DeadLetterQueue
from src.pipeline.transformer import DataTransformer, _normalize_event_type, _parse_timestamp


def test_normalize_event_type():
    assert _normalize_event_type("invite_sent") == "INVITE_SENT"
    assert _normalize_event_type("accepted") == "ACCEPTED"
    assert _normalize_event_type("connected") == "ACCEPTED"
    assert _normalize_event_type("reply") == "REPLY_RECEIVED"
    assert _normalize_event_type("meeting_booked") == "MEETING_BOOKED"


def test_parse_timestamp():
    dt = _parse_timestamp("2026-08-15T10:30:00Z")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 8
    assert dt.day == 15


def test_transformer_events(sample_raw_events):
    dlq = DeadLetterQueue()
    transformer = DataTransformer(dlq=dlq)
    clean = transformer.transform_outreach_events(sample_raw_events)

    assert len(clean) == 3
    assert clean[0]["event_type"] == "INVITE_SENT"
    assert clean[1]["event_type"] == "ACCEPTED"
    assert clean[2]["event_type"] == "REPLY_RECEIVED"
    assert dlq.count == 0


def test_transformer_bad_events(sample_bad_events):
    dlq = DeadLetterQueue()
    transformer = DataTransformer(dlq=dlq)
    clean = transformer.transform_outreach_events(sample_bad_events)

    assert len(clean) == 0
    assert dlq.count == len(sample_bad_events)
