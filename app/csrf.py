"""CSRF token helpers for API requests."""

import logging
import secrets

from fastapi import Request, Response

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/auth/csrf",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/register",
        "/api/v1/auth/csrf",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/register",
    }
)


def is_secure_request(request: Request) -> bool:
    """Determine whether the original client request was HTTPS.

    Respects reverse-proxy forwarded proto headers when present.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


def generate_csrf_token() -> str:
    """Generate a CSRF token suitable for double-submit cookie checks."""
    return secrets.token_urlsafe(32)


def is_csrf_protected_request(method: str, path: str) -> bool:
    """Return whether a request should pass CSRF validation."""
    normalized_path = path.rstrip("/") or "/"
    return method.upper() in CSRF_PROTECTED_METHODS and normalized_path not in _CSRF_EXEMPT_PATHS


def log_csrf_rejection(request: Request) -> None:
    """Emit a secret-free structured diagnostic for a CSRF rejection.

    Args:
        request: Request rejected by double-submit CSRF validation.

    Returns:
        None.
    """
    logger.warning(
        "CSRF request rejected",
        extra={
            "event": "auth_csrf" if "/auth/" in request.url.path else "csrf",
            "auth_outcome": "rejected",
            "auth_reason": "csrf_rejected",
            "path": request.url.path,
            "request_id": getattr(request.state, "request_id", None),
            "level": "WARNING",
        },
    )


def set_csrf_cookie(response: Response, request: Request, token: str) -> None:
    """Persist the CSRF token in a readable cookie for the frontend."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=is_secure_request(request),
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24,
    )


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    """Return the current CSRF token, creating and setting one if needed."""
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if token:
        return token

    token = generate_csrf_token()
    set_csrf_cookie(response, request, token)
    return token
