"""Unit tests for the _historical_observations function in comic_pile/bandwidth.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from comic_pile.bandwidth import _historical_observations
from app.services.bandwidth_inference import HistoricalObservation


@pytest.mark.asyncio
async def test_historical_observations_processes_rate_events_correctly():
    """Test that _historical_observations correctly processes rate events and creates observations."""
    # Mock the database session
    db = AsyncMock()
    
    # Mock the result of the first database query (get rate events)
    mock_rate_result = AsyncMock()
    mock_rate_scalars = AsyncMock()
    
    # Create a mock rate event
    from app.models import Event
    mock_rate_event = MagicMock(spec=Event)
    mock_rate_event.session_id = 1
    mock_rate_event.thread_id = 1
    mock_rate_event.source_roll_event_id = 100  # Link to roll event ID 100
    mock_rate_event.rating = 4.5
    mock_rate_event.issue_id = 10
    mock_rate_event.timestamp = MagicMock()  # We'll mock the hour property later
    
    mock_rate_scalars.all.return_value = [mock_rate_event]  # One rate event
    mock_rate_result.scalars.return_value = mock_rate_scalars
    
    # Mock the result of the second database query (get roll event)
    mock_roll_result = AsyncMock()
    mock_roll_scalars = AsyncMock()
    
    # Create a mock roll event
    mock_roll_event = MagicMock(spec=Event)
    mock_roll_event.selected_thread_id = 1  # Matches the rate event's thread_id
    mock_roll_event.timestamp = MagicMock()  # We'll mock the hour property later
    
    mock_roll_scalars.one_or_none.return_value = mock_roll_event
    mock_roll_result.scalars.return_value = mock_roll_scalars
    
    # Set up the side effect for db.execute to return different results for different queries
    def execute_side_effect(query):
        query_str = str(query)
        if "Event.session_id.is_not(None)" in query_str and "Event.type == \"rate\"" in query_str:
            return mock_rate_result
        elif "Event.id ==" in query_str:  # Roll event query
            return mock_roll_result
        else:
            # Default return for any other queries
            default_result = AsyncMock()
            default_scalars = AsyncMock()
            default_scalars.all.return_value = []
            default_result.scalars.return_value = default_scalars
            return default_result
    
    db.execute.side_effect = execute_side_effect
    
    # Mock the timestamp properties to return specific hours
    # Set rate event timestamp to return hour 10 (morning)
    mock_rate_event.timestamp.hour = 10
    # Set roll event timestamp to return hour 9 (morning)
    mock_roll_event.timestamp.hour = 9
    
    # Mock the compute_effort_estimate function to return a specific effort value
    with patch('app.services.reading_effort.compute_effort_estimate') as mock_compute_effort:
        # Set up the mock to return a light effort estimate (5 minutes)
        mock_effort_estimate = MagicMock()
        mock_effort_estimate.minutes = 5.0
        mock_compute_effort.return_value = mock_effort_estimate
        
        # Call the function
        result = await _historical_observations(db, user_id=1)
        
        # Verify the result contains one observation
        assert len(result) == 1
        observation = result[0]
        
        # Verify the observation has the expected values
        assert isinstance(observation, HistoricalObservation)
        assert observation.effort_minutes == 5.0
        assert observation.was_snoozed == False  # Default value (we didn't test snooze logic)
        assert observation.session_hour == 9  # From the roll event timestamp
        assert observation.rating == 4.5  # From the rate event
        
        # Verify that the mocks were called appropriately
        assert db.execute.call_count == 2  # One for rate events, one for roll event
        mock_compute_effort.assert_called_once_with(
            db,
            user_id=1,
            thread_id=1,
            issue_id=10
        )


@pytest.mark.asyncio
async def test_historical_observations_handles_missing_roll_event():
    """Test that _historical_observations skips rate events when roll event is missing."""
    # Mock the database session
    db = AsyncMock()
    
    # Mock the result of the first database query (get rate events)
    mock_rate_result = AsyncMock()
    mock_rate_scalars = AsyncMock()
    
    # Create a mock rate event
    from app.models import Event
    mock_rate_event = MagicMock(spec=Event)
    mock_rate_event.session_id = 1
    mock_rate_event.thread_id = 1
    mock_rate_event.source_roll_event_id = 999  # Link to non-existent roll event
    mock_rate_event.rating = 3.0
    mock_rate_event.issue_id = 5
    
    mock_rate_scalars.all.return_value = [mock_rate_event]  # One rate event
    mock_rate_result.scalars.return_value = mock_rate_scalars
    
    # Mock the result of the second database query (get roll event) - returns None
    mock_roll_result = AsyncMock()
    mock_roll_scalars = AsyncMock()
    mock_roll_scalars.one_or_none.return_value = None  # No roll event found
    mock_roll_result.scalars.return_value = mock_roll_scalars
    
    # Set up the side effect for db.execute to return different results for different queries
    def execute_side_effect(query):
        query_str = str(query)
        if "Event.session_id.is_not(None)" in query_str and "Event.type == \"rate\"" in query_str:
            return mock_rate_result
        elif "Event.id ==" in query_str:  # Roll event query
            return mock_roll_result
        else:
            # Default return for any other queries
            default_result = AsyncMock()
            default_scalars = AsyncMock()
            default_scalars.all.return_value = []
            default_result.scalars.return_value = default_scalars
            return default_result
    
    db.execute.side_effect = execute_side_effect
    
    # Mock the compute_effort_estimate function (should not be called in this case)
    with patch('app.services.reading_effort.compute_effort_estimate') as mock_compute_effort:
        # Call the function
        result = await _historical_observations(db, user_id=1)
        
        # Verify the result is empty (no observations created due to missing roll event)
        assert len(result) == 0
        
        # Verify that compute_effort_estimate was NOT called since we skipped the rate event
        mock_compute_effort.assert_not_called()


@pytest.mark.asyncio
async def test_historical_observations_handles_mismatched_thread_ids():
    """Test that _historical_observations skips rate events when thread IDs don't match."""
    # Mock the database session
    db = AsyncMock()
    
    # Mock the result of the first database query (get rate events)
    mock_rate_result = AsyncMock()
    mock_rate_scalars = AsyncMock()
    
    # Create a mock rate event
    from app.models import Event
    mock_rate_event = MagicMock(spec=Event)
    mock_rate_event.session_id = 1
    mock_rate_event.thread_id = 1  # Rate event is for thread 1
    mock_rate_event.source_roll_event_id = 100  # Link to roll event ID 100
    mock_rate_event.rating = 3.0
    mock_rate_event.issue_id = 5
    
    mock_rate_scalars.all.return_value = [mock_rate_event]  # One rate event
    mock_rate_result.scalars.return_value = mock_rate_scalars
    
    # Mock the result of the second database query (get roll event) - but with different thread ID
    mock_roll_result = AsyncMock()
    mock_roll_scalars = AsyncMock()
    
    # Create a mock roll event for thread 2 (different from rate event's thread 1)
    mock_roll_event = MagicMock(spec=Event)
    mock_roll_event.selected_thread_id = 2  # Different from rate event's thread_id
    mock_roll_scalars.one_or_none.return_value = mock_roll_event
    mock_roll_result.scalars.return_value = mock_roll_scalars
    
    # Set up the side effect for db.execute to return different results for different queries
    def execute_side_effect(query):
        query_str = str(query)
        if "Event.session_id.is_not(None)" in query_str and "Event.type == \"rate\"" in query_str:
            return mock_rate_result
        elif "Event.id ==" in query_str:  # Roll event query
            return mock_roll_result
        else:
            # Default return for any other queries
            default_result = AsyncMock()
            default_scalars = AsyncMock()
            default_scalars.all.return_value = []
            default_result.scalars.return_value = default_scalars
            return default_result
    
    db.execute.side_effect = execute_side_effect
    
    # Mock the compute_effort_estimate function (should not be called in this case)
    with patch('app.services.reading_effort.compute_effort_estimate') as mock_compute_effort:
        # Call the function
        result = await _historical_observations(db, user_id=1)
        
        # Verify the result is empty (no observations created due to mismatched thread IDs)
        assert len(result) == 0
        
        # Verify that compute_effort_estimate was NOT called since we skipped the rate event
        mock_compute_effort.assert_not_called()