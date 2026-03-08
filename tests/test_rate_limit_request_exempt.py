"""Regression tests for request-aware rate-limit exemptions."""

import importlib

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import app.middleware.rate_limit as rate_limit_module


@pytest.mark.asyncio
async def test_request_aware_exempt_when_receives_request() -> None:
    """Rate-limit exemptions should receive the current request when they expect one."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("TEST_ENVIRONMENT", "true")
    monkeypatch.setenv("ENABLE_RATE_LIMITING_IN_TESTS", "true")
    reloaded_rate_limit_module = importlib.reload(rate_limit_module)
    limiter = reloaded_rate_limit_module.limiter
    limiter.reset()
    path = "/api/test-rate-limit/request-aware-exempt"
    temp_app = FastAPI()
    temp_app.state.limiter = limiter
    temp_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    def exempt_when(request: Request) -> bool:
        return request.headers.get("x-bypass-rate-limit") == "true"

    async def endpoint(request: Request) -> dict[str, bool]:
        return {"ok": request.headers.get("x-bypass-rate-limit") == "true"}

    decorated_endpoint = limiter.limit("1/minute", exempt_when=exempt_when)(endpoint)
    temp_app.add_api_route(path, decorated_endpoint, methods=["GET"])

    transport = ASGITransport(app=temp_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bypass_one = await client.get(path, headers={"x-bypass-rate-limit": "true"})
        bypass_two = await client.get(path, headers={"x-bypass-rate-limit": "true"})

        assert bypass_one.status_code == 200
        assert bypass_two.status_code == 200

        limited_one = await client.get(path)
        limited_two = await client.get(path)

        assert limited_one.status_code == 200
        assert limited_two.status_code == 429

    limiter.reset()
    monkeypatch.undo()
    importlib.reload(rate_limit_module)
