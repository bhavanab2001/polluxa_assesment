"""
Account-level risk scoring model.

Combines anomaly scores across multiple outreach metrics into a
single Account Risk Score (0-100). Factors in the Account Age tier
ceiling from Part 1 as a hard constraint.

Risk levels:
- Green:  0-30  (healthy operations)
- Amber: 31-60  (caution, review needed)
- Red:   61-100 (critical, immediate action)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.analytics.anomaly import AnomalyDetector, AnomalyResult
from src.logging_config import get_logger

logger = get_logger("risk_model")


@dataclass
class AgentRiskProfile:
    """Risk profile for a single LinkedIn agent."""
    agent_key: int
    agent_id: str
    display_name: str | None
    tier_name: str | None
    risk_score: float  # 0-100
    risk_level: str  # Green, Amber, Red
    anomaly_results: dict[str, AnomalyResult]
    recommended_daily_invites: int | None
    recommended_daily_messages: int | None
    justification: str


class RiskModel:
    """
    Combines anomaly detection results into an account-level risk score.

    Metric weights for risk scoring:
    - Acceptance rate collapse:  30%
    - Reply rate decay:          25%
    - Ghosting rate:             20%
    - Utilisation anomaly:       15%
    - Activity volume anomaly:   10%
    """

    METRIC_WEIGHTS = {
        "acceptance_rate": 0.30,
        "reply_rate": 0.25,
        "ghosting_rate": 0.20,
        "utilisation": 0.15,
        "activity_volume": 0.10,
    }

    def __init__(self, session: Session, baseline_window: int = 14):
        self.session = session
        self.detector = AnomalyDetector(baseline_window=baseline_window)

    def score_agent(self, agent_key: int) -> AgentRiskProfile:
        """
        Compute the risk score for a single agent.

        Fetches daily activity data, runs anomaly detection on each
        metric, and combines into a weighted risk score.
        """
        # Fetch agent metadata
        agent_info = self.session.execute(
            text("""
                SELECT a.agent_id, a.display_name, t.tier_name,
                       t.daily_invite_limit, t.daily_message_limit
                FROM dim_agent a
                LEFT JOIN dim_account_tier t ON a.tier_key = t.tier_key
                WHERE a.agent_key = :ak AND a.is_current = true
            """),
            {"ak": agent_key},
        ).fetchone()

        agent_id = agent_info[0] if agent_info else f"agent_{agent_key}"
        display_name = agent_info[1] if agent_info else None
        tier_name = agent_info[2] if agent_info else None
        tier_invite_limit = agent_info[3] if agent_info else None
        tier_message_limit = agent_info[4] if agent_info else None

        # Fetch daily activity time series (ordered by date)
        rows = self.session.execute(
            text("""
                SELECT date_key, invites_sent, invites_accepted,
                       messages_sent, replies_received,
                       acceptance_rate, reply_rate, utilisation_pct
                FROM fact_daily_agent_activity
                WHERE agent_key = :ak
                ORDER BY date_key ASC
            """),
            {"ak": agent_key},
        ).fetchall()

        anomaly_results: dict[str, AnomalyResult] = {}

        if len(rows) < 6:
            # Insufficient data — cannot model risk
            return AgentRiskProfile(
                agent_key=agent_key,
                agent_id=agent_id,
                display_name=display_name,
                tier_name=tier_name,
                risk_score=0.0,
                risk_level="Green",
                anomaly_results={},
                recommended_daily_invites=tier_invite_limit,
                recommended_daily_messages=tier_message_limit,
                justification="Insufficient historical data for risk assessment (< 6 days).",
            )

        # Extract time series
        acceptance_rates = [float(r[5]) for r in rows if r[5] is not None]
        reply_rates = [float(r[6]) for r in rows if r[6] is not None]
        invites = [int(r[1]) for r in rows]
        accepted = [int(r[2]) for r in rows]
        replies = [int(r[4]) for r in rows]
        utilisation = [float(r[7]) for r in rows if r[7] is not None]

        # Run anomaly detection on each metric
        if len(acceptance_rates) >= 6:
            anomaly_results["acceptance_rate"] = self.detector.detect_rate_collapse(
                acceptance_rates, "acceptance_rate"
            )
        if len(reply_rates) >= 6:
            anomaly_results["reply_rate"] = self.detector.detect_rate_collapse(
                reply_rates, "reply_rate"
            )
        if len(accepted) >= 6 and len(replies) >= 6:
            anomaly_results["ghosting_rate"] = self.detector.detect_ghosting(
                accepted, replies
            )
        if len(utilisation) >= 6:
            anomaly_results["utilisation"] = self.detector.detect(
                utilisation, "utilisation"
            )
        if len(invites) >= 6:
            anomaly_results["activity_volume"] = self.detector.detect(
                [float(i) for i in invites], "activity_volume"
            )

        # Compute weighted risk score
        risk_score = 0.0
        for metric, weight in self.METRIC_WEIGHTS.items():
            if metric in anomaly_results:
                # Map anomaly_score (0,1,2) to risk contribution (0, 50, 100)
                anomaly_val = anomaly_results[metric].anomaly_score
                contribution = anomaly_val * 50 * weight
                risk_score += contribution

        risk_score = min(round(risk_score, 1), 100.0)

        # Determine risk level
        if risk_score <= 30:
            risk_level = "Green"
        elif risk_score <= 60:
            risk_level = "Amber"
        else:
            risk_level = "Red"

        # Compute recommended capacity
        rec_invites, rec_messages, justification = self._recommend_capacity(
            risk_score, risk_level, tier_invite_limit, tier_message_limit,
            anomaly_results,
        )

        profile = AgentRiskProfile(
            agent_key=agent_key,
            agent_id=agent_id,
            display_name=display_name,
            tier_name=tier_name,
            risk_score=risk_score,
            risk_level=risk_level,
            anomaly_results=anomaly_results,
            recommended_daily_invites=rec_invites,
            recommended_daily_messages=rec_messages,
            justification=justification,
        )

        logger.info(
            "agent_risk_scored",
            agent_id=agent_id,
            risk_score=risk_score,
            risk_level=risk_level,
        )

        return profile

    def score_all_agents(self) -> list[AgentRiskProfile]:
        """Score all current agents and update their anomaly scores."""
        agent_keys = self.session.execute(
            text("SELECT agent_key FROM dim_agent WHERE is_current = true")
        ).fetchall()

        profiles: list[AgentRiskProfile] = []
        for (ak,) in agent_keys:
            profile = self.score_agent(ak)
            profiles.append(profile)

            # Update the latest daily activity record with the anomaly score
            self.session.execute(
                text("""
                    UPDATE fact_daily_agent_activity
                    SET anomaly_score = :score
                    WHERE agent_key = :ak
                    AND date_key = (
                        SELECT MAX(date_key) FROM fact_daily_agent_activity WHERE agent_key = :ak
                    )
                """),
                {"score": profile.risk_score / 50, "ak": ak},  # Normalize to 0-2 scale
            )

        self.session.commit()
        logger.info("all_agents_scored", count=len(profiles))
        return profiles

    def _recommend_capacity(
        self,
        risk_score: float,
        risk_level: str,
        tier_invite_limit: int | None,
        tier_message_limit: int | None,
        anomaly_results: dict[str, AnomalyResult],
    ) -> tuple[int | None, int | None, str]:
        """
        Recommend adjusted daily capacity limits based on risk.

        Rules:
        - Green: maintain tier ceiling
        - Amber: reduce by 20%
        - Red: halve capacity

        Hard constraint: never exceed tier ceiling from Part 1.
        """
        if tier_invite_limit is None:
            return None, None, "No tier assigned — cannot compute recommendation."

        if risk_level == "Green":
            return (
                tier_invite_limit,
                tier_message_limit,
                f"Low risk ({risk_score}). Maintaining tier ceiling: "
                f"{tier_invite_limit} invites, {tier_message_limit} messages/day.",
            )
        elif risk_level == "Amber":
            rec_invites = int(tier_invite_limit * 0.8)
            rec_messages = int((tier_message_limit or 0) * 0.8)
            triggers = [
                m for m, r in anomaly_results.items() if r.anomaly_score >= 1
            ]
            return (
                rec_invites,
                rec_messages,
                f"Moderate risk ({risk_score}). Reducing to 80% capacity: "
                f"{rec_invites} invites, {rec_messages} messages/day. "
                f"Triggered by: {', '.join(triggers)}.",
            )
        else:  # Red
            rec_invites = int(tier_invite_limit * 0.5)
            rec_messages = int((tier_message_limit or 0) * 0.5)
            triggers = [
                m for m, r in anomaly_results.items() if r.anomaly_score >= 2
            ]
            return (
                rec_invites,
                rec_messages,
                f"HIGH RISK ({risk_score}). Halving capacity: "
                f"{rec_invites} invites, {rec_messages} messages/day. "
                f"Critical triggers: {', '.join(triggers)}. Immediate review recommended.",
            )
