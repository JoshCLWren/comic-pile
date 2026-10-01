"""Per-request performance diagnostics for database activity."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class RequestDiagnostics:
    request_id: str | None = None
    route: str | None = None
    database_queries: int = 0
    database_time_ms: float = 0.0


_request_diagnostics: ContextVar[RequestDiagnostics | None] = ContextVar(
    "request_diagnostics", default=None
)


def begin_request_diagnostics(
    *, request_id: str | None = None, route: str | None = None
) -> Token[RequestDiagnostics | None]:
    return _request_diagnostics.set(RequestDiagnostics(request_id=request_id, route=route))


def end_request_diagnostics(token: Token[RequestDiagnostics | None]) -> None:
    _request_diagnostics.reset(token)


def get_request_diagnostics() -> RequestDiagnostics:
    return _request_diagnostics.get() or RequestDiagnostics()


def record_database_query(duration_ms: float) -> None:
    diagnostics = _request_diagnostics.get()
    if diagnostics is None:
        return
    diagnostics.database_queries += 1
    diagnostics.database_time_ms += duration_ms
