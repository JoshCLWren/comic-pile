#!/usr/bin/env python3

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.performance_diagnostics import get_request_diagnostics, record_database_query

async def measure_current_queries():
    """Measure the current number of database queries in the roll_bootstrap endpoint."""
    
    # Clear any existing diagnostics
    diagnostics = get_request_diagnostics()
    if diagnostics is not None:
        # Reset the diagnostics
        from app.performance_diagnostics import _request_diagnostics
        _request_diagnostics.reset(_request_diagnostics.get())
    
    async with AsyncSessionLocal() as db:
        # Start a request context (simulating an HTTP request)
        token = await app.state.request_diagnostics.begin_request_diagnostics(
            request_id="test-request",
            route="/api/roll/bootstrap"
        )
        
        try:
            # Call the bootstrap endpoint logic directly
            from app.api.roll import roll_bootstrap
            from app.auth import get_current_user
            
            # Mock the current user
            user = await get_current_user(None)  # This would normally get from request
            user_id = user.id if user else 1  # Fallback to user_id=1
            
            # Call the bootstrap function
            result = await roll_bootstrap(
                current_user=type('obj', (object,), {'id': user_id})(),
                db=db
            )
            
            # Get the diagnostics
            diagnostics = get_request_diagnostics()
            query_count = diagnostics.database_queries
            print(f"Current bootstrap query count: {query_count}")
            print(f"Database time (ms): {diagnostics.database_time_ms}")
            
            return query_count
            
        finally:
            # End the request context
            from app.performance_diagnostics import end_request_diagnostics
            end_request_diagnostics(token)

if __name__ == "__main__":
    result = asyncio.run(measure_current_queries())
    print(f"Final query count: {result}")