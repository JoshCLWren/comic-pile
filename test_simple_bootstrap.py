#!/usr/bin/env python3

import asyncio
import sys
import os

# Add the comic-pile directory to the path
sys.path.insert(0, '/home/runner/work/comic-pile/comic-pile')

# Mock the async_session fixture
class MockAsyncSession:
    def __init__(self):
        self._queries = 0
        
    async def execute(self, stmt):
        self._queries += 1
        print(f"Executing query {self._queries}: {stmt}")
        # Return a mock result
        class MockResult:
            def scalars(self):
                return self
            def first(self):
                return None
        return MockResult()
        
    async def commit(self):
        pass

async def test_bootstrap_queries():
    """Test the number of queries in the roll_bootstrap endpoint."""
    
    # Create a mock session with query counting
    mock_session = MockAsyncSession()
    
    # Monkey patch the actual database session with our mock
    import app.api.roll
    original_get_db = app.api.roll.get_db
    
    async def mock_get_db():
        return mock_session
        
    app.api.roll.get_db = mock_get_db
    
    try:
        # Import and run the test
        from tests.test_roll_api import test_roll_bootstrap_does_not_flag_fresh_threads_as_stale
        
        # Create a sample data dict similar to what the test expects
        sample_data = {
            "threads": [
                {
                    "id": 1,
                    "title": "Thread 1",
                    "format": "Comic",
                    "queue_position": 1,
                    "status": "active",
                    "last_activity_at": datetime.now(UTC),
                    "created_at": datetime.now(UTC),
                    "total_issues": 5,
                    "reading_progress": 0.5,
                    "next_unread_issue_id": 2
                },
                {
                    "id": 2,
                    "title": "Thread 2",
                    "format": "Comic",
                    "queue_position": 2,
                    "status": "active",
                    "last_activity_at": datetime.now(UTC),
                    "created_at": datetime.now(UTC),
                    "total_issues": 3,
                    "reading_progress": 0.3,
                    "next_unread_issue_id": None
                }
            ],
            "user": {
                "id": 1
            }
        }
        
        # Run the test
        await test_roll_bootstrap_does_not_flag_fresh_threads_as_stale(
            auth_client=type('obj', (object,), {
                'get': lambda url: type('obj', (object,), {
                    'json': lambda: {
                        'id': 1,
                        'pending_thread_id': 1
                    },
                    'status_code': 200
                })(),
                async_db=mock_session
            ),
            async_db=mock_session
        )
        
        print(f"Total queries executed: {mock_session._queries}")
        return mock_session._queries
        
    finally:
        # Restore original function
        app.api.roll.get_db = original_get_db

if __name__ == "__main__":
    result = asyncio.run(test_bootstrap_queries())
    print(f"Query count: {result}")