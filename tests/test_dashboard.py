from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

import api.security as security
from api.main import app
from core.storage.database import get_session

_AUTH = ("operator", "dashboard-password")


class _FakeResult:
    def __init__(self, records: list[object]) -> None:
        self._records = records

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return self._records


class _FakeSession:
    def __init__(self, results: list[list[object]]) -> None:
        self._results = iter(results)

    def execute(self, _statement: object) -> _FakeResult:
        return _FakeResult(next(self._results))


@pytest.fixture
def dashboard_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    settings = SimpleNamespace(api_username=_AUTH[0], api_password=SecretStr(_AUTH[1]))
    monkeypatch.setattr(security, "get_settings", lambda: settings)

    event = SimpleNamespace(
        timestamp=datetime(2026, 7, 28, 15, 56, 58, tzinfo=UTC),
        severity=85,
        source_ip="203.0.113.10",
        host_name="edge-01",
        dataset="host_agent.auth",
        category=["authentication"],
        outcome="failure",
        message="Fehlgeschlagener SSH-Login",
    )
    alert = SimpleNamespace(
        created_at=datetime(2026, 7, 28, 15, 57, 1, tzinfo=UTC),
        severity=90,
        title="SSH Brute Force",
        description="Mehrere fehlgeschlagene Anmeldungen",
        rule_id="brute_force_ssh",
        mitre_technique="T1110",
        host_name="edge-01",
        source_ip="203.0.113.10",
    )

    def fake_session() -> Iterator[Session]:
        yield cast(Session, _FakeSession([[event], [alert]]))

    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_dashboard_renders_live_data_in_reference_layout(dashboard_client: TestClient) -> None:
    response = dashboard_client.get("/", auth=_AUTH)

    assert response.status_code == 200
    assert "Ereignisstrom" in response.text
    assert "Fehlgeschlagener SSH-Login" in response.text
    assert "SSH Brute Force" in response.text
    assert "AUTO-REFRESH · 3 S" in response.text
    assert "geplant" in response.text
    assert 'data-host="edge-01"' in response.text
    assert 'datetime="2026-07-28T15:56:58+00:00"' in response.text
    assert "htmx" not in response.text.casefold()
    assert "https://" not in response.text


def test_dashboard_accepts_validated_filters(dashboard_client: TestClient) -> None:
    response = dashboard_client.get(
        "/?host=edge-01&category=authentication&min_severity=80&search=SSH",
        auth=_AUTH,
    )

    assert response.status_code == 200
    assert 'value="edge-01"' in response.text
    assert 'value="80" selected' in response.text
