"""Security headers middleware for FastAPI application."""

import os


from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses.

    Adds the following security headers:
    - Content-Security-Policy (CSP): Prevents XSS attacks
    - Strict-Transport-Security (HSTS): Enforces HTTPS
    - X-Content-Type-Options: Prevents MIME sniffing
    - X-Frame-Options: Prevents clickjacking
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add security headers to the response.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response with security headers added.
        """
        response = await call_next(request)

        # Add Content Security Policy header
        # This is a restrictive CSP that allows resources from same origin,
        # inline styles/scripts, and specific external sources needed for the app
        csp_header = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-src 'none';"
        )
        response.headers["Content-Security-Policy"] = csp_header

        # Add HTTP Strict Transport Security header
        # Only add HSTS in production environments
        environment = os.getenv("APP_ENV", os.getenv("ENV", "development"))
        if environment == "production":
            # HSTS with 2 years max age, includeSubDomains, and preload
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        else:
            # Shorter duration for development
            response.headers["Strict-Transport-Security"] = "max-age=300"

        # Add X-Content-Type-Options header to prevent MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Add X-Frame-Options header to prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Additional security headers
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        return response
