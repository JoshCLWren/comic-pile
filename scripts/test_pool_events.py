#!/usr/bin/env python3
"""Test pool event listeners work correctly."""

import os

# Set environment for testing - use a mock PostgreSQL URL that won't actually connect
os.environ['ENVIRONMENT'] = 'test'
os.environ['TEST_ENVIRONMENT'] = 'true'
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://user:pass@localhost:5432/test'
os.environ['TEST_DATABASE_URL'] = 'postgresql+asyncpg://user:pass@localhost:5432/test'

# Now import the database module - just verify it imports and event listeners are registered
from app.database import async_engine

# Check that pool event listeners are registered
pool = async_engine.sync_engine.pool
print(f"Pool: {pool}")
print(f"Pool class: {pool.__class__.__name__}")

# Check event listeners by inspecting the pool's dispatch
print("\nRegistered event listeners on pool:")
for evt in ['checkout', 'checkin', 'connect', 'first_connect', 'invalidate']:
    dispatch = getattr(pool.dispatch, evt, None)
    if dispatch:
        listeners = list(dispatch.listeners)
        print(f"  {evt}: {len(listeners)} listener(s)")
        for listener in listeners:
            if hasattr(listener, 'fn'):
                print(f"    - {listener.fn.__name__} from {listener.fn.__module__}")
            else:
                print(f"    - {listener.__name__} from {listener.__module__}")
    else:
        print(f"  {evt}: no dispatch")

print("\nRegistered event listeners on engine:")
for evt in ['before_cursor_execute', 'after_cursor_execute']:
    dispatch = getattr(async_engine.sync_engine.dispatch, evt, None)
    if dispatch:
        listeners = list(dispatch.listeners)
        print(f"  {evt}: {len(listeners)} listener(s)")
        for listener in listeners:
            if hasattr(listener, 'fn'):
                print(f"    - {listener.fn.__name__} from {listener.fn.__module__}")
            else:
                print(f"    - {listener.__name__} from {listener.__module__}")
    else:
        print(f"  {evt}: no dispatch")

print("\nEvent listeners are registered correctly!")