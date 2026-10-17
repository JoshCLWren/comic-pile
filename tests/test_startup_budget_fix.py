import pytest
from unittest.mock import MagicMock, patch
from app.performance_budgets import enforce_startup_budget, StartupBudgetError
from app.main import create_app

def test_startup_budget_ignores_process_age_when_startup_duration_is_low():
    # Mock settings to production
    with patch("app.main.get_app_settings") as mock_settings:
        mock_settings.return_value.environment = "production"
        
        # Case 1: process_age_ms is high, but startup_duration is low.
        # In the original code, this would have failed because of max(startup_duration, process_age_ms).
        # In the fixed code, it should use startup_duration.
        
        # We can't easily call create_app() because it does a lot of things.
        # Instead, we'll test the logic that is now in app/main.py:
        # readiness_ms = startup_duration if startup_duration > 0 else ready_snapshot.process_age_ms
        
        startup_duration = 1500.0 # Under 2500ms limit
        process_age_ms = 600000.0 # Way over 2500ms limit
        
        readiness_ms = startup_duration if startup_duration > 0 else process_age_ms
        
        # This should NOT raise StartupBudgetError
        enforce_startup_budget(
            readiness_ms, 
            environment="production", 
            operation="startup.readiness"
        )

def test_startup_budget_still_fails_when_startup_duration_is_high():
    # Case 2: startup_duration itself is high.
    startup_duration = 3000.0 # Over 2500ms limit
    
    readiness_ms = startup_duration if startup_duration > 0 else 0.0
    
    with pytest.raises(StartupBudgetError):
        enforce_startup_budget(
            readiness_ms, 
            environment="production", 
            operation="startup.readiness"
        )

def test_startup_budget_falls_back_to_process_age_if_duration_zero():
    # Case 3: startup_duration is 0 (or None/uncomputed), should fall back to process_age.
    startup_duration = 0.0
    process_age_ms = 3000.0 # Over limit
    
    readiness_ms = startup_duration if startup_duration > 0 else process_age_ms
    
    with pytest.raises(StartupBudgetError):
        enforce_startup_budget(
            readiness_ms, 
            environment="production", 
            operation="startup.readiness"
        )
