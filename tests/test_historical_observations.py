"""Unit tests for the _historical_observations function in comic_pile/bandwidth.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from comic_pile.bandwidth import _historical_observations
from app.services.bandwidth_inference import HistoricalObservation


@pytest.mark.asyncio
async def test_historical_observations_returns_empty_list_when_no_data():
    """Test that _historical_observations returns empty list when no historical data exists."""
    # Mock the database session
    db = AsyncMock()
    
    # Mock the result of the database query chain
    mock_result = AsyncMock()
    mock_scalars = AsyncMock()
    mock_scalars.all.return_value = []  # No rate events
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    
    # Mock the result of the reading_effort service calls
    with patch('app.services.reading_effort.collect_classified_observations') as mock_collect, \
         patch('app.services.reading_effort.aggregate_observations') as mock_aggregate, \
         patch('app.services.reading_effort.resolve_publication_year') as mock_pub_year, \
         patch('app.services.reading_effort.compute_effort_estimate') as mock_compute_effort:
        
        # Set up mocks to return empty/no data
        mock_collect.return_value = []  # No classified observations
        mock_aggregate.return_value = ({}, {})  # No issue/thread aggregates
        mock_pub_year.return_value = None  # No publication year
        mock_compute_effort.return_value = MagicMock(minutes=None)  # No effort estimate
        
        # Call the function
        result = await _historical_observations(db, user_id=1)
        
        # Verify the result
        assert result == []
        
        # Verify that the mocks were called
        db.execute.assert_called_once()
        mock_collect.assert_called_once_with(db, 1)
        mock_aggregate.assert_called_once_with([])
        mock_pub_year.assert_not_called()  # Should not be called if no observations
        mock_compute_effort.assert_not_called()  # Should not be called if no observations


@pytest.mark.asyncio
async def test_historical_observations_processes_light_history():
    """Test that _historical_observations correctly processes light-effort history."""
    # Mock the database session
    db = AsyncMock()
    
    # Mock the result of the database query chain for rate events
    mock_result = AsyncMock()
    mock_scalars = AsyncMock()
    
    # Create a mock rate event
    from app.models import Event
    mock_rate_event = MagicMock(spec=Event)
    mock_rate_event.session_id = 1
    mock_rate_event.thread_id = 1
    mock_rate_event.source_roll_event_id = 1
    mock_rate_event.rating = None
    mock_rate_event.issue_id = 1
    
    mock_scalars.all.return_value = [mock_rate_event]  # One rate event
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    
    # Mock the result of the database query for roll events
    mock_roll_result = AsyncMock()
    mock_roll_scalars = AsyncMock()
    mock_roll_event = MagicMock(spec=Event)
    mock_roll_event.selected_thread_id = 1
    mock_roll_result.scalars.return_value = mock_roll_scalars
    mock_roll_scalars.one_or_none.return_value = mock_roll_event
    
    # Set up the side effect for db.execute to return different results for different queries
    def execute_side_effect(query):
        if "Event.session_id.is_not(None)" in str(query) and "Event.type == \"rate\"" in str(query):
            return mock_result
        else:  # Roll event query
            return mock_roll_result
    
    db.execute.side_effect = execute_side_effect
    
    # Create mock classified observations
    from app.services.reading_effort import ClassifiedObservation, DurationObservation
    
    # Create a mock duration observation (light effort: 5 minutes = 300 seconds)
    duration_obs = DurationObservation(
        roll_event_id=1,
        rate_event_id=2,
        session_id=1,
        thread_id=1,
        issue_id=1,
        elapsed_seconds=300.0  # 5 minutes
    )
    
    # Create a classified observation (valid light effort)
    classified_obs = ClassifiedObservation(
        observation=duration_obs,
        valid=True,
        reason_code=None
    )
    
    # Mock the result of the reading_effort service calls
    with patch('app.services.reading_effort.collect_classified_observations') as mock_collect, \
         patch('app.services.reading_effort.aggregate_observations') as mock_aggregate, \
         patch('app.services.reading_effort.resolve_publication_year') as mock_pub_year, \
         patch('app.services.reading_effort.compute_effort_estimate') as mock_compute_effort:
        
        # Set up mocks to return light-effort data
        mock_collect.return_value = [classified_obs]  # One light-effort observation
        mock_aggregate.return_value = (
            {(1, 1): MagicMock(minutes=5.0, sample_count=1)},  # Issue aggregate
            {1: MagicMock(minutes=5.0, sample_count=1)}       # Thread aggregate
        )
        mock_pub_year.return_value = None  # No publication year
        mock_compute_effort.return_value = MagicMock(minutes=5.0)  # 5 minutes effort
        
        # Call the function
        result = await _historical_observations(db, user_id=1)
        
        # Verify the result contains one observation
        assert len(result) == 1
        observation = result[0]
        
        # Verify the observation has the expected values
        assert isinstance(observation, HistoricalObservation)
        assert observation.effort_minutes == 5.0
        assert observation.was_snoozed == False  # Default value
        assert observation.session_hour is not None  # Should be set from session start time
        assert observation.rating is None  # Default value when not provided


@pytest.mark.asyncio
async def test_historical_observations_processes_heavy_history():
    """Test that _historical_observations correctly processes heavy-effort history."""
    # Mock the database session
    db = AsyncMock()
    
    # Mock the result of the database query chain for rate events
    mock_result = AsyncMock()
    mock_scalars = AsyncMock()
    
    # Create a mock rate event
    from app.models import Event
    mock_rate_event = MagicMock(spec=Event)
    mock_rate_event.session_id = 1
    mock_rate_event.thread_id = 1
    mock_rate_event.source_roll_event_id = 1
    mock_rate_event.rating = None
    mock_rate_event.issue_id = 1
    
    mock_scalars.all.return_value = [mock_rate_event]  # One rate event
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    
    # Mock the result of the database query for roll events
    mock_roll_result = AsyncMock()
    mock_roll_scalars = AsyncMock()
    mock_roll_event = MagicMock(spec=Event)
    mock_roll_event.selected_thread_id = 1
    mock_roll_result.scalars.return_value = mock_roll_scalars
    mock_roll_scalars.one_or_none.return_value = mock_roll_event
    
    # Set up the side effect for db.execute to return different results for different queries
    def execute_side_effect(query):
        if "Event.session_id.is_not(None)" in str(query) and "Event.type == \"rate\"" in str(query):
            return mock_result
        else:  # Roll event query
            return mock_roll_result
    
    db.execute.side_effect = execute_side_effect
    
    # Create mock classified observations
    from app.services.reading_effort import ClassifiedObservation, DurationObservation
    
    # Create a mock duration observation (heavy effort: 25 minutes = 1500 seconds)
    duration_obs = DurationObservation(
        roll_event_id=1,
        rate_event_id=2,
        session_id=1,
        thread_id=1,
        issue_id=1,
        elapsed_seconds=1500.0  # 25 minutes
    )
    
    # Create a classified observation (valid heavy effort)
    classified_obs = ClassifiedObservation(
        observation=duration_obs,
        valid=True,
        reason_code=None
    )
    
    # Mock the result of the reading_effort service calls
    with patch('app.services.reading_effort.collect_classified_observations') as mock_collect, \
         patch('app.services.reading_effort.aggregate_observations') as mock_aggregate, \
         patch('app.services.reading_effort.resolve_publication_year') as mock_pub_year, \
         patch('app.services.reading_effort.compute_effort_estimate') as mock_compute_effort:
        
        # Set up mocks to return heavy-effort data
        mock_collect.return_value = [classified_obs]  # One heavy-effort observation
        mock_aggregate.return_value = (
            {(1, 1): MagicMock(minutes=25.0, sample_count=1)},  # Issue aggregate
            {1: MagicMock(minutes=25.0, sample_count=1)}       # Thread aggregate
        )
        mock_pub_year.return_value = None  # No publication year
        mock_compute_effort.return_value = MagicMock(minutes=25.0)  # 25 minutes effort
        
        # Call the function
        result = await _historical_observations(db, user_id=1)
        
        # Verify the result contains one observation
        assert len(result) == 1
        observation = result[0]
        
        # Verify the observation has the expected values
        assert isinstance(observation, HistoricalObservation)
        assert observation.effort_minutes == 25.0
        assert observation.was_snoozed == False  # Default value
        assert observation.session_hour is not None  # Should be set from session start time
        assert observation.rating is None  # Default value when not provided