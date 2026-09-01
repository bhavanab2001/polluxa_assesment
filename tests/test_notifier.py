"""Unit tests for the AlertNotifier."""

import pytest
from unittest.mock import patch, MagicMock
from src.alerts.notifier import AlertNotifier, AlertLevel


def test_alert_notifier_fallback_logging():
    notifier = AlertNotifier()
    # When no webhook or SMTP is configured, send_alert still logs and returns False
    result = notifier.send_alert(
        title="Test Alert",
        message="This is a test alert notification.",
        level=AlertLevel.INFO,
        details={"metric": 100},
    )
    assert result is False


@patch("httpx.post")
def test_alert_notifier_webhook_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    notifier = AlertNotifier()
    notifier.webhook_url = "https://hooks.slack.com/services/test"

    success = notifier.send_alert(
        title="Pipeline Succeeded",
        message="All batches processed.",
        level=AlertLevel.INFO,
        details={"loaded": 1000},
    )
    assert success is True
    mock_post.assert_called_once()
