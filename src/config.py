"""
Configuration management for Polluxa Analytics Platform.

All settings are loaded from environment variables / .env file.
Zero secrets in source code.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataSourceMode(str, Enum):
    """How data is ingested into the pipeline."""
    API = "api"
    CSV = "csv"


class LogFormat(str, Enum):
    """Log output format."""
    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Priority: environment variables > .env file > defaults
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ─────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "polluxa_analytics"
    postgres_user: str = "polluxa"
    postgres_password: str = "changeme_secure_password"
    database_url: Optional[str] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_url(self) -> str:
        """Fully composed database URL."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Polluxa API ──────────────────────────────────────────
    polluxa_api_base_url: str = "https://sales.polluxa.com/api"
    polluxa_api_token: str = ""

    # ── Pipeline ─────────────────────────────────────────────
    data_source_mode: DataSourceMode = DataSourceMode.CSV
    csv_import_dir: Path = Path("./data/imports")
    loader_batch_size: int = 500

    # ── Rate Limiting ────────────────────────────────────────
    api_request_delay: float = 1.0
    api_max_retries: int = 3
    api_retry_base_delay: float = 2.0

    # ── Data Quality ─────────────────────────────────────────
    dq_pass_threshold: float = 85.0

    # ── Alerting ─────────────────────────────────────────────
    alert_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""

    # ── Logging ──────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON


# Singleton settings instance
settings = Settings()
