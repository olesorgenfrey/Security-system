from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://aegis:test@127.0.0.1/aegis",
        "redis_url": "redis://127.0.0.1:6379/0",
        "api_password": "test-dashboard-password",
        **overrides,
    }
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("address", ["127.0.0.1", "127.23.45.67", "::1", "[::1]"])
def test_auth_bypass_accepts_literal_loopback_addresses(address: str) -> None:
    settings = _settings(api_auth_disabled=True, api_public_bind_address=address)

    assert settings.api_auth_disabled is True


@pytest.mark.parametrize("address", ["0.0.0.0", "192.0.2.10", "::", "localhost"])
def test_auth_bypass_rejects_non_literal_or_non_loopback_addresses(address: str) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        _settings(api_auth_disabled=True, api_public_bind_address=address)
