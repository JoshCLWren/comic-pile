"""Mobile device detection utilities."""

import re

from fastapi import Request


MOBILE_USER_AGENTS = re.compile(
    r"Android|iPhone|iPad|iPod|Windows Phone|Mobile|Opera Mini|Kindle|Silk|PlayBook|BlackBerry",
    re.I,
)


def is_mobile_request(request: Request) -> bool:
    """Check if the request originates from a mobile device.

    Args:
        request: FastAPI request object.

    Returns:
        True if the User-Agent indicates a mobile device, False otherwise.
    """
    user_agent = request.headers.get("user-agent", "")
    return bool(MOBILE_USER_AGENTS.search(user_agent))
