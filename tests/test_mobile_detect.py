"""Tests for mobile device detection utilities."""

import pytest
from fastapi import Request
from unittest.mock import Mock

from app.utils.mobile_detect import is_mobile_request


@pytest.mark.asyncio
async def test_is_mobile_request_mobile_user_agents():
    """Test that mobile user agents are correctly detected."""
    mobile_agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15",
        "Mozilla/5.0 (Android 10; Mobile; rv:91.0) Gecko/91.0 Firefox/91.0",
        "Mozilla/5.0 (iPad; CPU OS 13_2 like Mac OS X) AppleWebKit/605.1.15",
        "Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; Microsoft; Lumia 950) AppleWebKit/537.36",
        "Opera/9.80 (J2ME/MIDP; Opera Mini/7.1.32052/30.3697; U; en) Presto/2.8.119 Version/11.10",
        "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36",
        "Mozilla/5.0 (BlackBerry; U; BlackBerry 9900; en) AppleWebKit/534.11+ (KHTML, like Gecko) Version/7.1.0.346 Mobile Safari/534.11+",
    ]

    for user_agent in mobile_agents:
        mock_request = Mock(spec=Request)
        mock_request.headers = {"user-agent": user_agent}
        assert is_mobile_request(mock_request) is True


@pytest.mark.asyncio
async def test_is_mobile_request_desktop_user_agents():
    """Test that desktop user agents are correctly identified as non-mobile."""
    desktop_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "curl/7.68.0",
        "",  # Empty user agent
        None,  # No user agent
    ]

    for user_agent in desktop_agents:
        mock_request = Mock(spec=Request)
        if user_agent is not None:
            mock_request.headers = {"user-agent": user_agent}
        else:
            mock_request.headers = {}
        assert is_mobile_request(mock_request) is False


@pytest.mark.asyncio
async def test_is_mobile_request_case_insensitive():
    """Test that mobile detection is case insensitive."""
    mock_request = Mock(spec=Request)
    mock_request.headers = {"user-agent": "MoZiLlA/5.0 (AnDrOiD 10) ApPlEwEbKiT/537.36"}
    assert is_mobile_request(mock_request) is True


@pytest.mark.asyncio
async def test_is_mobile_request_no_user_agent():
    """Test behavior when no user-agent header is present."""
    mock_request = Mock(spec=Request)
    mock_request.headers = {}  # No user-agent header
    assert is_mobile_request(mock_request) is False
