"""Dashboard (Phase 1): Live-Event-Feed + validierte Suche/Filter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from api.routes.alerts import build_alerts_query
from api.routes.events import build_events_query
from core.schemas.event import EventCategory
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


def dashboard_filters(
    host: Annotated[str, Query(max_length=255)] = "",
    category: EventCategory | Literal[""] = "",
    min_severity: Annotated[int, Query(ge=0, le=100)] = 0,
    search: Annotated[str, Query(max_length=500)] = "",
) -> DashboardFilters:
    """Validate dashboard filters before they are used to construct a query."""
    return DashboardFilters(
        host=host,
        category=category.value if isinstance(category, EventCategory) else category,
        min_severity=min_severity,
        search=search,
    )


@router.get("/")
def dashboard_index(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    filters: Annotated[DashboardFilters, Depends(dashboard_filters)],
) -> HTMLResponse:
    stmt = build_events_query(
        filters.host or None,
        filters.category or None,
        filters.min_severity,
        filters.search or None,
    ).limit(100)
    events = session.execute(stmt).scalars().all()
    alerts = session.execute(build_alerts_query("open").limit(20)).scalars().all()
    host_count = len({event.host_name for event in events})
    critical_alert_count = sum(alert.severity >= 80 for alert in alerts)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_view": "feed",
            "page_title": "Live-Feed",
            "events": events,
            "alerts": alerts,
            "filters": filters,
            "categories": [category.value for category in EventCategory],
            "alert_count": len(alerts),
            "critical_alert_count": critical_alert_count,
            "host_count": host_count,
        },
    )


@router.get("/alerts")
def dashboard_alerts(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    alerts = session.execute(build_alerts_query("open").limit(20)).scalars().all()
    return templates.TemplateResponse(
        request,
        "alerts.html",
        {
            "active_view": "alerts",
            "page_title": "Alerts",
            "alerts": alerts,
            "alert_count": len(alerts),
            "critical_alert_count": sum(alert.severity >= 80 for alert in alerts),
            "alert_host_count": len({alert.host_name for alert in alerts if alert.host_name}),
            "alert_source_count": len(
                {str(alert.source_ip) for alert in alerts if alert.source_ip}
            ),
        },
    )


@router.get("/partials/alerts")
def alerts_partial(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> HTMLResponse:
    alerts = session.execute(build_alerts_query("open").limit(20)).scalars().all()
    return templates.TemplateResponse(request, "_alerts_table.html", {"alerts": alerts})


@router.get("/partials/events")
def events_partial(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    filters: Annotated[DashboardFilters, Depends(dashboard_filters)],
) -> HTMLResponse:
    stmt = build_events_query(
        filters.host or None,
        filters.category or None,
        filters.min_severity,
        filters.search or None,
    ).limit(100)
    events = session.execute(stmt).scalars().all()
    return templates.TemplateResponse(request, "_events_table.html", {"events": events})
