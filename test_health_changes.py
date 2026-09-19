#!/usr/bin/env python3

import asyncio
import time
from app.services.health_probe import (
    ProbeError, ProbeTimeoutError, ProbeUnavailableError, ProbeNotConfiguredError,
    _timed_probe, database_probe, cache_probe, get_dependency_health
)
from unittest.mock import AsyncMock, MagicMock

async def test_probe_timeout():
    """Test that timeout handling works correctly"""
    async def failing_operation():
        # Sleep longer than the timeout to trigger the exception
        await asyncio.sleep(3.0)  # This will timeout after 2 seconds
    
    result = await _timed_probe(failing_operation)
    assert result.status == "timeout"
    print("✓ Timeout probe test passed")

async def test_probe_success():
    """Test that successful probe works"""
    async def successful_operation():
        return "success"
    
    result = await _timed_probe(successful_operation)
    assert result.status == "healthy"
    print("✓ Success probe test passed")

async def test_probe_exception():
    """Test that ProbeError is properly caught"""
    async def failing_operation():
        raise ProbeError("test error")
    
    result = await _timed_probe(failing_operation)
    assert result.status == "unavailable"
    print("✓ Exception probe test passed")

async def main():
    print("Testing health probe changes...")
    await test_probe_timeout()
    await test_probe_success()
    await test_probe_exception()
    print("All tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
