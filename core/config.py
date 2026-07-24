"""Zentrale Konfiguration. Wird per Umgebungsvariablen (.env) befüllt."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://aegis:aegis@localhost:5432/aegis"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"
    scope_file: str = "config/scope.yaml"

    # Host-Agent (Phase 1)
    host_agent_hostname: str = "localhost"
    host_agent_log_paths: str = "/var/log/auth.log"
    """Kommagetrennte Liste zu tailender Log-Dateien."""
    host_agent_snapshot_interval_seconds: int = 15
    """Intervall für Prozess-/Netzwerk-Snapshots."""

    # Alerting (Phase 1: erste Benachrichtigungen)
    notify_severity_threshold: int = 70
    """Ab dieser Severity (0-100) wird eine Benachrichtigung ausgelöst."""
    notify_webhook_url: str | None = None
    notify_email_to: str | None = None
    notify_email_from: str = "aegis@localhost"
    notify_smtp_host: str | None = None
    notify_smtp_port: int = 587
    notify_smtp_user: str | None = None
    notify_smtp_password: str | None = None

    # Detection Engine (Phase 2)
    detection_brute_force_threshold: int = 3
    """Ab so vielen Fehlversuchen derselben Quell-IP im Zeitfenster entsteht ein Alert."""
    detection_brute_force_window_minutes: int = 5
    detection_brute_force_cooldown_minutes: int = 15
    """Mindestabstand zwischen zwei Alerts derselben Regel/IP, um Alert-Flut zu vermeiden."""


@lru_cache
def get_settings() -> Settings:
    return Settings()
