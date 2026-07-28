"""Authentication and browser-facing response hardening for the web application."""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import get_settings

_AUTH_CHALLENGE = 'Basic realm="Aegis", charset="UTF-8"'
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'; object-src 'none'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

RequestHandler = Callable[[Request], Awaitable[Response]]


def _secure_headers(response: Response, *, is_https: bool) -> Response:
    for name, value in _SECURITY_HEADERS.items():
        response.headers[name] = value
    if is_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def _credentials(authorization: str | None) -> tuple[str, str]:
    """Decode an HTTP Basic header without leaking parsing failures to callers."""
    if authorization is None:
        return "", ""

    scheme, separator, encoded = authorization.partition(" ")
    if not separator or scheme.casefold() != "basic" or not encoded:
        return "", ""

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return "", ""

    username, separator, password = decoded.partition(":")
    if not separator:
        return "", ""
    return username, password


def _constant_time_equal(candidate: str, expected: str) -> bool:
    """Compare fixed-size digests so arbitrary Unicode credentials are supported."""
    candidate_digest = hashlib.sha256(candidate.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return secrets.compare_digest(candidate_digest, expected_digest)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Protect every route except the container health probe and harden responses."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        is_https = request.url.scheme == "https"
        if request.url.path == "/health":
            return _secure_headers(await call_next(request), is_https=is_https)

        settings = get_settings()
        if not settings.api_username or not settings.api_password:
            return _secure_headers(
                JSONResponse(
                    {"detail": "API authentication is not configured"},
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                ),
                is_https=is_https,
            )

        expected_password = settings.api_password.get_secret_value()
        username, password = _credentials(request.headers.get("Authorization"))
        username_matches = _constant_time_equal(username, settings.api_username)
        password_matches = _constant_time_equal(password, expected_password)
        if not (username_matches and password_matches):
            return _secure_headers(
                JSONResponse(
                    {"detail": "Authentication required"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": _AUTH_CHALLENGE},
                ),
                is_https=is_https,
            )

        return _secure_headers(await call_next(request), is_https=is_https)
