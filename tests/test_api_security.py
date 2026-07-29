from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import api.security as security
from api.main import app

client = TestClient(app)
_AUTH = ("operator", "correct horse battery staple")


@pytest.fixture
def configured_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        api_username=_AUTH[0],
        api_password=SecretStr(_AUTH[1]),
        api_auth_disabled=False,
        api_public_bind_address="127.0.0.1",
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)


def test_health_is_public_and_hardened() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


def test_hsts_is_only_sent_over_https() -> None:
    https_client = TestClient(app, base_url="https://testserver")

    response = https_client.get("/health")

    assert response.status_code == 200
    assert response.headers["strict-transport-security"].startswith("max-age=")


@pytest.mark.usefixtures("configured_auth")
def test_protected_route_challenges_missing_credentials() -> None:
    response = client.get("/api/info")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert response.headers["www-authenticate"] == 'Basic realm="Aegis", charset="UTF-8"'
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.usefixtures("configured_auth")
@pytest.mark.parametrize("path", ["/", "/alerts", "/docs", "/openapi.json", "/does-not-exist"])
def test_every_non_health_route_is_protected(path: str) -> None:
    response = client.get(path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")


@pytest.mark.usefixtures("configured_auth")
@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer token",
        "Basic !!!not-base64!!!",
        "Basic d2l0aG91dC1jb2xvbg==",
    ],
)
def test_protected_route_rejects_malformed_credentials(authorization: str) -> None:
    response = client.get("/api/info", headers={"Authorization": authorization})

    assert response.status_code == 401
    assert "Basic" in response.headers["www-authenticate"]


@pytest.mark.usefixtures("configured_auth")
def test_protected_route_accepts_configured_credentials() -> None:
    response = client.get("/api/info", auth=_AUTH)

    assert response.status_code == 200
    assert response.json()["name"] == "aegis"
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers


@pytest.mark.usefixtures("configured_auth")
def test_static_assets_are_also_protected() -> None:
    unauthorized = client.get("/static/style.css")
    authorized = client.get("/static/style.css", auth=_AUTH)

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.headers["cache-control"] == "no-store"


def test_unconfigured_auth_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        api_username="aegis",
        api_password=None,
        api_auth_disabled=False,
        api_public_bind_address="127.0.0.1",
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)

    response = client.get("/api/info", auth=("aegis", "anything"))

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_explicit_local_test_mode_bypasses_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        api_username="aegis",
        api_password=SecretStr("unused-dashboard-password"),
        api_auth_disabled=True,
        api_public_bind_address="127.0.0.1",
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)

    response = client.get("/api/info")

    assert response.status_code == 200
    assert response.json()["name"] == "aegis"
    assert response.headers["cache-control"] == "no-store"


def test_test_mode_still_fails_closed_on_non_loopback_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        api_username="aegis",
        api_password=SecretStr("unused-dashboard-password"),
        api_auth_disabled=True,
        api_public_bind_address="0.0.0.0",
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)

    response = client.get("/api/info")

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication bypass requires a loopback binding"}
    assert response.headers["cache-control"] == "no-store"


def test_dashboard_has_no_remote_script_dependency() -> None:
    template = Path("dashboard/templates/base.html").read_text(encoding="utf-8")

    assert "htmx" not in template.casefold()
    assert "https://" not in template
    assert 'src="/static/dashboard.js"' in template
