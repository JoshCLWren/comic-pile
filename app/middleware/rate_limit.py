"""Rate limiting middleware using slowapi."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

TEST_MODE = os.getenv("TEST_ENVIRONMENT") == "true"


def _should_enable_rate_limiting() -> bool:
    """Check if rate limiting should be enabled."""
    if not TEST_MODE:
        return True
    return os.getenv("ENABLE_RATE_LIMITING_IN_TESTS") == "true"


if TEST_MODE:
    def _test_rate_limit_key(request: Request) -> str:
        """Derive test-mode rate limit key from auth context, falling back to client address."""
        auth_header = request.headers.get("authorization")
        if auth_header:
            return auth_header
        return get_remote_address(request)

    # In test mode, create a limiter but override the limit method to do nothing
    _real_limiter = Limiter(key_func=_test_rate_limit_key, default_limits=["1000000/second"])

    class NoOpLimiter:
        """No-op limiter for test mode that bypasses rate limiting."""

        def __getattr__(self, name):
            """Proxy all other attributes to real limiter."""
            return getattr(_real_limiter, name)

        def limit(self, limit_value: str):
            """Return a decorator that conditionally applies rate limiting."""

            def decorator(func):
                if _should_enable_rate_limiting():
                    return _real_limiter.limit(limit_value)(func)
                return func

            return decorator

    limiter = NoOpLimiter()
else:
    limiter = Limiter(key_func=get_remote_address)
