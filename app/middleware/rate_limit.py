"""Rate limiting middleware using slowapi."""

import os
from collections.abc import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

TEST_MODE = os.getenv("TEST_ENVIRONMENT") == "true"
RateLimitValue = str | Callable[..., str]


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

    class TestLimiter(Limiter):
        """Limiter that can dynamically exempt requests while tests are running."""

        def limit(
            self,
            limit_value: RateLimitValue,
            key_func: Callable[..., str] | None = None,
            per_method: bool = False,
            methods: list[str] | None = None,
            error_message: RateLimitValue | None = None,
            exempt_when: Callable[..., bool] | None = None,
            cost: int | Callable[..., int] = 1,
            override_defaults: bool = True,
        ) -> Callable:
            """Return a decorator that exempts requests unless rate limiting is enabled."""

            def _test_exempt_when() -> bool:
                if not _should_enable_rate_limiting():
                    return True
                if exempt_when is None:
                    return False
                return exempt_when()

            return super().limit(
                limit_value,
                key_func=key_func,
                per_method=per_method,
                methods=methods,
                error_message=error_message,
                exempt_when=_test_exempt_when,
                cost=cost,
                override_defaults=override_defaults,
            )

    limiter = TestLimiter(key_func=_test_rate_limit_key, default_limits=["1000000/second"])
else:
    limiter = Limiter(key_func=get_remote_address)
