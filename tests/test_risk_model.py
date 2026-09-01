"""Unit tests for the Risk Scoring Model."""

from src.analytics.risk_model import AgentRiskProfile


def test_agent_risk_profile_dataclass():
    profile = AgentRiskProfile(
        agent_key=1,
        agent_id="agent_001",
        display_name="Test Agent",
        tier_name="Tier 1",
        risk_score=15.0,
        risk_level="Green",
        anomaly_results={},
        recommended_daily_invites=25,
        recommended_daily_messages=50,
        justification="Within normal parameters",
    )
    assert profile.agent_id == "agent_001"
    assert profile.risk_level == "Green"
    assert profile.risk_score == 15.0
