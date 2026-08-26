"""Domain exceptions raised by services and mapped to HTTP by routers.

Services stay framework-free: they raise these plain exceptions and routers
translate them into ``HTTPException`` responses with the correct status code
and detail message.
"""


class ServiceError(Exception):
    """Base class for domain errors carrying a client-safe detail string."""

    def __init__(self, detail: str) -> None:
        """Store the client-facing detail message.

        Args:
            detail: Human-readable message safe to return to API clients.
        """
        self.detail = detail
        super().__init__(detail)


class NotFoundError(ServiceError):
    """A referenced entity does not exist or is not owned by the caller."""


class InvalidRequestError(ServiceError):
    """A request is syntactically valid but semantically unacceptable."""


class ConflictError(ServiceError):
    """The request collides with existing state (duplicate key, stale order)."""


class ForbiddenError(ServiceError):
    """The caller is not authorized to perform this action."""
