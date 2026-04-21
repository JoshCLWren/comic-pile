"""Rate limiting middleware using slowapi."""

import asyncio
import contextvars
import functools
import inspect
import os
from collections.abc import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

RateLimitValue = str | Callable[..., str]
_current_request: contextvars.ContextVar[Request | None] = contextvars.ContextVar(
    "rate_limit_request",
    default=None,
)


def _is_test_mode() -> bool:
    """Return whether the current process is running under tests."""
    return os.getenv("TEST_ENVIRONMENT") == "true"


def _should_enable_rate_limiting() -> bool:
    """Check if rate limiting should be enabled."""
    if not _is_test_mode():
        return True
    return os.getenv("ENABLE_RATE_LIMITING_IN_TESTS") == "true"


def _rate_limit_key(request: Request) -> str:
    """Use auth-aware keys in tests and client IPs elsewhere."""
    if _is_test_mode():
        auth_header = request.headers.get("authorization")
        if auth_header:
            return auth_header
    return get_remote_address(request)


class DynamicTestLimiter(Limiter):
    """Limiter that defers test-mode exemptions until each request."""

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
        """Return a decorator that can disable limits during most tests."""
        expects_request = False
        if exempt_when is not None:
            signature = inspect.signature(exempt_when)
            expects_request = len(signature.parameters) == 1

        def _test_exempt_when() -> bool:
            if _is_test_mode() and not _should_enable_rate_limiting():
                return True
            if exempt_when is None:
                return False
            if expects_request:
                request = _current_request.get()
                if request is None:
                    return False
                return exempt_when(request)
            return exempt_when()

        limit_decorator = super().limit(
            limit_value,
            key_func=key_func,
            per_method=per_method,
            methods=methods,
            error_message=error_message,
            exempt_when=_test_exempt_when,
            cost=cost,
            override_defaults=override_defaults,
        )

        def decorator(func: Callable) -> Callable:
            limited_func = limit_decorator(func)
            if not expects_request:
                return limited_func

            request_parameter_index = next(
                (
                    index
                    for index, parameter in enumerate(inspect.signature(func).parameters.values())
                    if parameter.name == "request"
                ),
                -1,
            )

            if asyncio.iscoroutinefunction(limited_func):

                @functools.wraps(limited_func)
                async def async_with_request(*args, **kwargs):
                    request = kwargs.get("request")
                    if (
                        request is None
                        and request_parameter_index >= 0
                        and len(args) > request_parameter_index
                    ):
                        request = args[request_parameter_index]
                    token = _current_request.set(request if isinstance(request, Request) else None)
                    try:
                        return await limited_func(*args, **kwargs)
                    finally:
                        _current_request.reset(token)

                return async_with_request

            @functools.wraps(limited_func)
            def sync_with_request(*args, **kwargs):
                request = kwargs.get("request")
                if (
                    request is None
                    and request_parameter_index >= 0
                    and len(args) > request_parameter_index
                ):
                    request = args[request_parameter_index]
                token = _current_request.set(request if isinstance(request, Request) else None)
                try:
                    return limited_func(*args, **kwargs)
                finally:
                    _current_request.reset(token)

            return sync_with_request

        return decorator


limiter = DynamicTestLimiter(key_func=_rate_limit_key)
