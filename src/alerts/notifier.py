"""
Alert notifier — sends alerts on pipeline failure, DQ breach, and anomalous behavior.

Supports:
- Webhook (Slack, Microsoft Teams, custom)
- Email (SMTP)
- Console logging (fallback)
"""

from __future__ import annotations

import json
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

from src.config import settings
from src.logging_config import get_logger

logger = get_logger("notifier")


class AlertLevel:
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertNotifier:
    """
    Sends alerts through configured channels when pipeline issues occur.

    Alert triggers:
    1. Pipeline failure (status = FAILED)
    2. DQ score below threshold
    3. Anomalous pipeline run duration (> 2σ from mean)
    4. High-risk agent detected
    """

    def __init__(self):
        self.webhook_url = settings.alert_webhook_url
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.email_to = settings.alert_email_to

    def send_alert(
        self,
        title: str,
        message: str,
        level: str = AlertLevel.WARNING,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """
        Send an alert through all configured channels.

        Returns True if at least one channel succeeded.
        """
        success = False

        # Always log
        log_func = logger.warning if level == AlertLevel.WARNING else logger.error
        if level == AlertLevel.INFO:
            log_func = logger.info
        log_func("alert_triggered", title=title, level=level, message=message)

        # Webhook
        if self.webhook_url:
            try:
                self._send_webhook(title, message, level, details)
                success = True
            except Exception as exc:
                logger.error("webhook_alert_failed", error=str(exc))

        # Email
        if self.smtp_host and self.email_to:
            try:
                self._send_email(title, message, level, details)
                success = True
            except Exception as exc:
                logger.error("email_alert_failed", error=str(exc))

        if not success:
            logger.warning("no_alert_channels_configured", title=title)

        return success

    def alert_pipeline_failure(
        self, run_id: str, error_message: str, duration_seconds: float
    ) -> bool:
        """Send alert for pipeline execution failure."""
        return self.send_alert(
            title="🚨 Pipeline Failure",
            message=f"Pipeline run `{run_id}` failed after {duration_seconds:.1f}s.\n\nError: {error_message}",
            level=AlertLevel.CRITICAL,
            details={
                "run_id": run_id,
                "error": error_message,
                "duration_seconds": duration_seconds,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def alert_dq_breach(
        self, run_id: str, score: float, threshold: float, dimension_scores: dict[str, float] | None = None
    ) -> bool:
        """Send alert when DQ score falls below threshold."""
        return self.send_alert(
            title="⚠️ Data Quality Breach",
            message=(
                f"Pipeline run `{run_id}` DQ score: **{score:.1f}%** "
                f"(threshold: {threshold}%).\n\n"
                f"Dimension scores: {dimension_scores or 'N/A'}"
            ),
            level=AlertLevel.WARNING,
            details={
                "run_id": run_id,
                "dq_score": score,
                "threshold": threshold,
                "dimension_scores": dimension_scores,
            },
        )

    def alert_anomalous_duration(
        self, run_id: str, duration: float, mean_duration: float, std_duration: float
    ) -> bool:
        """Send alert when pipeline run duration is anomalous (> 2σ)."""
        z_score = (duration - mean_duration) / std_duration if std_duration > 0 else 0
        return self.send_alert(
            title="⏱️ Anomalous Pipeline Duration",
            message=(
                f"Pipeline run `{run_id}` took **{duration:.1f}s** "
                f"(mean: {mean_duration:.1f}s, σ: {std_duration:.1f}s, Z: {z_score:.1f})."
            ),
            level=AlertLevel.WARNING,
            details={
                "run_id": run_id,
                "duration_seconds": duration,
                "mean_duration": mean_duration,
                "std_duration": std_duration,
                "z_score": z_score,
            },
        )

    def alert_high_risk_agent(
        self, agent_id: str, risk_score: float, risk_level: str, justification: str
    ) -> bool:
        """Send alert when an agent is classified as high risk."""
        return self.send_alert(
            title=f"🔴 High Risk Agent: {agent_id}",
            message=f"Agent `{agent_id}` risk score: **{risk_score}** ({risk_level}).\n\n{justification}",
            level=AlertLevel.CRITICAL if risk_level == "Red" else AlertLevel.WARNING,
            details={
                "agent_id": agent_id,
                "risk_score": risk_score,
                "risk_level": risk_level,
            },
        )

    def _send_webhook(
        self, title: str, message: str, level: str, details: dict | None
    ) -> None:
        """Send alert via webhook (Slack/Teams compatible)."""
        # Slack-compatible payload
        color_map = {
            AlertLevel.INFO: "#36a64f",
            AlertLevel.WARNING: "#ff9900",
            AlertLevel.CRITICAL: "#ff0000",
        }

        payload = {
            "text": title,
            "attachments": [
                {
                    "color": color_map.get(level, "#808080"),
                    "title": title,
                    "text": message,
                    "fields": [
                        {"title": k, "value": str(v), "short": True}
                        for k, v in (details or {}).items()
                    ],
                    "ts": int(datetime.now(timezone.utc).timestamp()),
                }
            ],
        }

        response = httpx.post(
            self.webhook_url,
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        logger.info("webhook_alert_sent", url=self.webhook_url)

    def _send_email(
        self, title: str, message: str, level: str, details: dict | None
    ) -> None:
        """Send alert via SMTP email."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{level}] {title}"
        msg["From"] = self.smtp_user
        msg["To"] = self.email_to

        # Plain text body
        body = f"{title}\n\n{message}"
        if details:
            body += f"\n\nDetails:\n{json.dumps(details, indent=2, default=str)}"

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

        logger.info("email_alert_sent", to=self.email_to)
