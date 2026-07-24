"""FastAPI-Einstiegspunkt. Phase 1: Event-API + Dashboard. Phase 2: Alert-API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes import alerts, dashboard, events
from core.config import get_settings

app = FastAPI(title="Aegis", description="Adaptive Defensive Security Platform")

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent.parent / "dashboard" / "static")),
    name="static",
)

app.include_router(events.router)
app.include_router(alerts.router)
app.include_router(dashboard.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/info")
def info() -> dict[str, str]:
    settings = get_settings()
    return {"name": "aegis", "log_level": settings.log_level}
