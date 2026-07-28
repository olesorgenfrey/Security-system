from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import api.security as security
from api.main import app

client = TestClient(app)
_AUTH = ("operator", "test-password")


@pytest.fixture(autouse=True)
def configured_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        api_username=_AUTH[0],
        api_password=SecretStr(_AUTH[1]),
        api_auth_disabled=False,
        api_public_bind_address="127.0.0.1",
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)


@pytest.mark.parametrize(
    "path",
    [
        "/api/events?min_severity=not-a-number",
        "/api/events?min_severity=-1",
        "/api/events?min_severity=101",
        "/api/events?category=made_up",
        f"/api/events?host={'h' * 256}",
        f"/api/events?search={'x' * 501}",
        "/api/events?limit=0",
        "/api/events?limit=1001",
        "/api/alerts?status=made_up",
        "/api/alerts?limit=0",
        "/api/alerts?limit=501",
        "/partials/events?min_severity=not-a-number",
        "/partials/events?min_severity=101",
        "/partials/events?category=made_up",
        f"/partials/events?host={'h' * 256}",
        "/?min_severity=not-a-number",
    ],
)
def test_invalid_query_parameters_return_422(path: str) -> None:
    response = client.get(path, auth=_AUTH)

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
