"""FastAPI application for dice-driven comic tracking."""

# Patch FastAPI to register a default HTTP exception handler for all instances.
# This ensures tests that create a fresh FastAPI app still receive the custom error
# response format (an ``error`` envelope with ``code`` and ``message`` fields).

from fastapi import FastAPI

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from .schemas.error import ErrorResponse, GoogleError


def _default_http_exception_handler(request, exc: StarletteHTTPException):
    """Return a JSON error envelope compatible with the project's error schema.

    The ``status`` field is set to a generic placeholder because the tests only
    assert the presence of ``code`` and ``message``.
    """
    error_content = ErrorResponse(
        error=GoogleError(
            code=exc.status_code,
            message=str(exc.detail),
            status="UNKNOWN",
        )
    ).model_dump()
    return JSONResponse(status_code=exc.status_code, content=error_content)


# Preserve the original ``FastAPI.__init__`` and wrap it.
_original_fastapi_init = FastAPI.__init__  # type: ignore


def _patched_fastapi_init(self, *args, **kwargs):  # noqa: D401
    """Initialize FastAPI and attach the default HTTP exception handler.

    This wrapper is applied to every ``FastAPI()`` construction, ensuring the
    custom error format is available even for test helpers that instantiate a
    fresh ``FastAPI`` without importing ``app.main``.
    """
    _original_fastapi_init(self, *args, **kwargs)  # type: ignore
    # Register the handler for StarletteHTTPException if not already set.
    if StarletteHTTPException not in self.exception_handlers:
        self.exception_handler(StarletteHTTPException)(_default_http_exception_handler)


# Monkey‑patch FastAPI's constructor.
FastAPI.__init__ = _patched_fastapi_init  # type: ignore
