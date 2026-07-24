"""Dashboard (Phase 1): Live-Event-Feed + einfache Suche/Filter (HTMX + Jinja)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.routes.alerts import build_alerts_query
from api.routes.events import build_events_query
from core.storage.database import get_session

router = APIRouter(tags=["dashboard"])
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "dashboard" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@dataclass
class DashboardFilters:
    host: str
    category: str
    min_severity: int
    search: str


def _filters(request: Request) -> DashboardFilters:
    q = request.query_params
    return DashboardFilters(
        host=q.get("host") or "",
        category=q.get("category") or "",
        min_severity=int(q.get("min_severity") or 0),
        search=q.get("search") or "",
    )


@router.get("/")
def dashboard_index(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    filters = _filters(request)
    stmt = build_events_query(
        filters.host or None,
        filters.category or None,
        filters.min_severity,
        filters.search or None,
    ).limit(100)
    events = session.execute(stmt).scalars().all()
    alerts = session.execute(build_alerts_query("open").limit(20)).scalars().all()
    return templates.TemplateResponse(
        request, "index.html", {"events": events, "alerts": alerts, "filters": filters}
    )


@router.get("/partials/alerts")
def alerts_partial(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    alerts = session.execute(build_alerts_query("open").limit(20)).scalars().all()
    return templates.TemplateResponse(request, "_alerts_table.html", {"alerts": alerts})


@router.get("/partials/events")
def events_partial(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    filters = _filters(request)
    stmt = build_events_query(
        filters.host or None,
        filters.category or None,
        filters.min_severity,
        filters.search or None,
    ).limit(100)
    events = session.execute(stmt).scalars().all()
    return templates.TemplateResponse(
        request, "_events_table.html", {"events": events}
    )
