#!/usr/bin/env python3
"""Test pool configuration via environment variables."""

import os
import sys

def test_pool_config():
    """Test that pool configuration is read from environment variables."""
    # Test 1: Default configuration (optimized for Vercel Fluid Compute)
    for key in ['DB_POOL_SIZE', 'DB_MAX_OVERFLOW', 'DB_POOL_PRE_PING', 'DB_POOL_RECYCLE']:
        if key in os.environ:
            del os.environ[key]
    
    # Clear module cache and reimport
    if 'app.database' in sys.modules:
        del sys.modules['app.database']
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    from app.database import POOL_SIZE, MAX_OVERFLOW, POOL_PRE_PING, POOL_RECYCLE
    
    assert POOL_SIZE == 2, f"Expected POOL_SIZE=2, got {POOL_SIZE}"
    assert MAX_OVERFLOW == 0, f"Expected MAX_OVERFLOW=0, got {MAX_OVERFLOW}"
    assert POOL_PRE_PING is False, f"Expected POOL_PRE_PING=False, got {POOL_PRE_PING}"
    assert POOL_RECYCLE == 3600, f"Expected POOL_RECYCLE=3600, got {POOL_RECYCLE}"
    print("✓ Test 1 passed: Default configuration (optimized)")
    
    # Test 2: Custom configuration
    os.environ['DB_POOL_SIZE'] = '3'
    os.environ['DB_MAX_OVERFLOW'] = '0'
    os.environ['DB_POOL_PRE_PING'] = 'false'
    os.environ['DB_POOL_RECYCLE'] = '1800'
    
    if 'app.database' in sys.modules:
        del sys.modules['app.database']
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    from app.database import POOL_SIZE, MAX_OVERFLOW, POOL_PRE_PING, POOL_RECYCLE
    
    assert POOL_SIZE == 3, f"Expected POOL_SIZE=3, got {POOL_SIZE}"
    assert MAX_OVERFLOW == 0, f"Expected MAX_OVERFLOW=0, got {MAX_OVERFLOW}"
    assert POOL_PRE_PING is False, f"Expected POOL_PRE_PING=False, got {POOL_PRE_PING}"
    assert POOL_RECYCLE == 1800, f"Expected POOL_RECYCLE=1800, got {POOL_RECYCLE}"
    print("✓ Test 2 passed: Custom configuration")
    
    # Test 3: Pool pre_ping case insensitive
    os.environ['DB_POOL_PRE_PING'] = 'TRUE'
    
    if 'app.database' in sys.modules:
        del sys.modules['app.database']
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    from app.database import POOL_PRE_PING
    
    assert POOL_PRE_PING is True, f"Expected POOL_PRE_PING=True, got {POOL_PRE_PING}"
    print("✓ Test 3 passed: Pool pre_ping case insensitive (TRUE)")
    
    os.environ['DB_POOL_PRE_PING'] = 'False'
    
    if 'app.database' in sys.modules:
        del sys.modules['app.database']
    if 'app.config' in sys.modules:
        del sys.modules['app.config']
    
    from app.database import POOL_PRE_PING
    
    assert POOL_PRE_PING is False, f"Expected POOL_PRE_PING=False, got {POOL_PRE_PING}"
    print("✓ Test 4 passed: Pool pre_ping case insensitive (False)")
    
    # Cleanup
    for key in ['DB_POOL_SIZE', 'DB_MAX_OVERFLOW', 'DB_POOL_PRE_PING', 'DB_POOL_RECYCLE']:
        if key in os.environ:
            del os.environ[key]
    
    print("\nAll pool configuration tests passed!")

if __name__ == "__main__":
    test_pool_config()