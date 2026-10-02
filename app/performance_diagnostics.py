"""Per-request performance diagnostics for database activity."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class RequestDiagnostics:
    """Mutable counters and context collected during one HTTP request."""

    request_id: str | None = None
    route: str | None = None
    database_queries: int = 0
    database_time_ms: float = 0.0


_request_diagnostics: ContextVar[RequestDiagnostics | None] = ContextVar(
    "request_diagnostics",
    default=None,
)


def begin_request_diagnostics(
    *,
    request_id: str | None = None,
    route: str | None = None,
) -> Token[RequestDiagnostics | None]:
    """Start a fresh diagnostics context for the current request.

    Args:
        request_id: Correlation identifier for the current HTTP request, when available.
        route: Request route associated with the diagnostics context, when available.

    Returns:
        ContextVar token used to restore the previous diagnostics context.
    """
    return _request_diagnostics.set(RequestDiagnostics(request_id=request_id, route=route))


def end_request_diagnostics(token: Token[RequestDiagnostics | None]) -> None:
    """Restore the diagnostics context that preceded the current request."""
    _request_diagnostics.reset(token)


def get_request_diagnostics() -> RequestDiagnostics:
    """Return the active diagnostics object or an empty detached snapshot."""
    return _request_diagnostics.get() or RequestDiagnostics()


def record_database_query(duration_ms: float) -> None:
    """Record one completed SQL query in the active request context."""
    diagnostics = _request_diagnostics.get()
    if diagnostics is None:
        return
    diagnostics.database_queries += 1
    diagnostics.database_time_ms += duration_ms
