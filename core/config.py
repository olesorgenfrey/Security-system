"""Zentrale Konfiguration. Wird per Umgebungsvariablen (.env) befüllt."""

from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def is_loopback_address(value: str) -> bool:
    """Return true only for literal IPv4/IPv6 loopback addresses."""
    candidate = value.strip().removeprefix("[").removesuffix("]")
    try:
        return ip_address(candidate).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    redis_url: str
    log_level: str = "INFO"
    scope_file: str = "config/scope.yaml"

    # API-Zugriffsschutz
    api_username: str = Field(default="aegis", min_length=1, pattern=r".*\S.*")
    api_password: SecretStr | None = Field(default=None, min_length=16)
    api_auth_disabled: bool = False
    api_public_bind_address: str = "127.0.0.1"

    @model_validator(mode="after")
    def validate_local_auth_bypass(self) -> Self:
        """Never allow the test-only auth bypass on a non-loopback binding."""
        if not self.api_auth_disabled:
            return self

        if not is_loopback_address(self.api_public_bind_address):
            raise ValueError(
                "API_AUTH_DISABLED may only be enabled with a literal loopback bind address"
            )
        return self

    # Redis-Stream-Ingestion
    ingestion_pending_idle_ms: int = Field(default=60_000, gt=0)
    """Ab diesem Leerlauf darf ein anderer Consumer eine Pending-Nachricht übernehmen."""
    ingestion_max_delivery_attempts: int = Field(default=5, gt=0)
    ingestion_recovery_batch_size: int = Field(default=50, gt=0)
    ingestion_recovery_interval_seconds: int = Field(default=30, gt=0)
    ingestion_error_backoff_seconds: int = Field(default=5, gt=0)
    ingestion_dlq_maxlen: int = Field(default=10_000, gt=0)

    # Host-Agent (Phase 1)
    host_agent_hostname: str = "localhost"
    host_agent_log_paths: str = "/var/log/auth.log"
    """Kommagetrennte Liste zu tailender Log-Dateien."""
    host_agent_snapshot_interval_seconds: int = Field(default=15, gt=0)
    """Intervall für Prozess-/Netzwerk-Snapshots."""

    # Alerting (Phase 1: erste Benachrichtigungen)
    notify_severity_threshold: int = Field(default=70, ge=0, le=100)
    """Ab dieser Severity (0-100) wird eine Benachrichtigung ausgelöst."""
    notify_webhook_url: str | None = None
    notify_email_to: str | None = None
    notify_email_from: str = "aegis@localhost"
    notify_smtp_host: str | None = None
    notify_smtp_port: int = Field(default=587, ge=1, le=65_535)
    notify_smtp_user: str | None = None
    notify_smtp_password: SecretStr | None = None
    notify_max_attempts: int = Field(default=5, gt=0)
    notify_retry_base_seconds: int = Field(default=30, gt=0)
    notify_retry_max_seconds: int = Field(default=3600, gt=0)
    notify_worker_poll_seconds: int = Field(default=5, gt=0)
    notify_worker_batch_size: int = Field(default=50, gt=0)

    # Detection Engine (Phase 2)
    detection_brute_force_threshold: int = Field(default=3, gt=0)
    """Ab so vielen Fehlversuchen derselben Quell-IP im Zeitfenster entsteht ein Alert."""
    detection_brute_force_window_minutes: int = Field(default=5, gt=0)
    detection_brute_force_cooldown_minutes: int = Field(default=15, ge=0)
    """Mindestabstand zwischen zwei Alerts derselben Regel/IP, um Alert-Flut zu vermeiden."""
    detection_keyword_cooldown_minutes: int = Field(default=15, ge=0)

    # Anomalie-Detektor (Phase 2): Z-Score auf Prozess-Erstellungsrate pro Host
    anomaly_window_seconds: int = Field(default=60, gt=0)
    anomaly_baseline_windows: int = Field(default=10, ge=3)
    """Anzahl vorheriger Zeitfenster, aus denen Mittelwert/Streuung berechnet werden."""
    anomaly_min_count: int = Field(default=5, gt=0)
    """Mindestanzahl Ereignisse im aktuellen Fenster, bevor Z-Score überhaupt geprüft wird."""
    anomaly_z_threshold: float = Field(default=3.0, gt=0)
    anomaly_cooldown_minutes: int = Field(default=15, ge=0)

    # Datenpflege
    event_retention_days: int = Field(default=90, gt=0)
    event_retention_batch_size: int = Field(default=1000, gt=0)
    maintenance_interval_seconds: int = Field(default=86_400, gt=0)


class HostAgentSettings(BaseSettings):
    """Minimal configuration for the host-level collector.

    The agent deliberately has no database setting, so its container never needs
    access to PostgreSQL credentials.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    redis_url: str
    log_level: str = "INFO"
    host_agent_hostname: str = "localhost"
    host_agent_log_paths: str = "/var/log/auth.log"
    host_agent_snapshot_interval_seconds: int = Field(default=15, gt=0)


@lru_cache
def get_settings() -> Settings:
    # Required connection URLs are supplied by BaseSettings from the environment.
    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_host_agent_settings() -> HostAgentSettings:
    return HostAgentSettings()  # type: ignore[call-arg]
