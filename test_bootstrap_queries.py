#!/usr/bin/env python3

import asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.main import app
from app.performance_diagnostics import get_request_diagnostics

async def measure_bootstrap_queries():
    """Measure the number of database queries in the roll_bootstrap endpoint."""
    
    # Clear any existing diagnostics
    diagnostics = get_request_diagnostics()
    if diagnostics is not None:
        # Reset the diagnostics
        from app.performance_diagnostics import _request_diagnostics
        _request_diagnostics.reset(_request_diagnostics.get())
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Get a session first to establish request context
        session_response = await client.get("/api/sessions/current/")
        print(f"Session endpoint response: {session_response.status_code}")
        
        # Now call the bootstrap endpoint
        bootstrap_response = await client.get("/api/roll/bootstrap")
        print(f"Bootstrap endpoint response: {bootstrap_response.status_code}")
        
        # Check the diagnostics
        diagnostics = get_request_diagnostics()
        print(f"Database queries: {diagnostics.database_queries}")
        print(f"Database time (ms): {diagnostics.database_time_ms}")
        
        return diagnostics.database_queries

if __name__ == "__main__":
    result = asyncio.run(measure_bootstrap_queries())
    print(f"Current bootstrap query count: {result}")