"""Safe, explicit connection settings for tests that do not open service connections."""

from __future__ import annotations

import os

# Application settings are intentionally required in production. Unit tests import
# the engine and Redis helpers but do not connect; service tests override these values.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://aegis_test:aegis_test@127.0.0.1:5432/aegis_test",
)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")
