"""Performance tests for auth refresh endpoint optimization."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request

from app.api.auth import refresh_access_token
from app.auth import create_refresh_token
from app.models.user import User
from app.schemas.auth import TokenResponse


@pytest.mark.asyncio
async def test_refresh_access_token_optimized():
    """Test that the optimized refresh endpoint works correctly."""
    # Mock database session
    mock_db = AsyncMock()
    
    # Mock request and response
    mock_request = Request(scope={"type": "http", "method": "POST", "path": "/refresh"})
    mock_response = AsyncMock()
    
    # Create a test refresh token
    test_username = "testuser"
    test_jti = "test_jti_123"
    test_refresh_token = create_refresh_token(
        data={"sub": test_username, "jti": test_jti, "type": "refresh", "pc": 0}
    )
    
    # Mock the optimized function to return user and not revoked
    async def mock_get_user_with_revocation_check(db, username, jti):
        user = User(id=1, username=username, email="test@example.com", password_hash="hashed")
        return user, False
    
    # Mock token verification
    with patch('app.api.auth.verify_token') as mock_verify:
        mock_verify.return_value = {
            "sub": test_username,
            "jti": test_jti,
            "type": "refresh",
            "pc": 0
        }
        
        with patch('app.api.auth.get_user_by_username_with_revocation_check', 
                   side_effect=mock_get_user_with_revocation_check):
            
            # Mock refresh token data
            with patch('app.api.auth.RefreshTokenRequest') as mock_request_data:
                mock_request_data.return_value.refresh_token = test_refresh_token
                
                # Mock cookie setting
                with patch('app.api.auth._set_refresh_cookie'):
                    # Mock CSRF cookie
                    with patch('app.api.auth.ensure_csrf_cookie'):
                        # Mock token creation
                        with patch('app.api.auth.create_access_token') as mock_create_access:
                            with patch('app.api.auth.create_refresh_token') as mock_create_refresh:
                                mock_create_access.return_value = "new_access_token"
                                mock_create_refresh.return_value = "new_refresh_token"
                                
                                # Call the optimized function
                                result = await refresh_access_token(
                                    request=mock_request,
                                    response=mock_response,
                                    db=mock_db,
                                    refresh_data=None
                                )
                                
                                # Verify the result
                                assert isinstance(result, TokenResponse)
                                assert result.access_token == "new_access_token"
                                assert result.refresh_token == "new_refresh_token"


@pytest.mark.asyncio
async def test_refresh_access_token_parallel_token_creation():
    """Test that tokens are created in parallel for better performance."""
    # Mock database session
    mock_db = AsyncMock()
    
    # Mock request and response
    mock_request = Request(scope={"type": "http", "method": "POST", "path": "/refresh"})
    mock_response = AsyncMock()
    
    test_username = "testuser"
    test_jti = "test_jti_123"
    test_refresh_token = create_refresh_token(
        data={"sub": test_username, "jti": test_jti, "type": "refresh", "pc": 0}
    )
    
    # Track timing of token creation
    token_creation_times = []
    
    async def slow_token_creation(data, delay=0.01):
        """Simulate token creation with timing."""
        token_creation_times.append(time.time())
        await asyncio.sleep(delay)
        return f"token_{data['jti']}"
    
    async def mock_get_user_with_revocation_check(db, username, jti):
        user = User(id=1, username=username, email="test@example.com", password_hash="hashed")
        return user, False
    
    with patch('app.api.auth.verify_token') as mock_verify:
        mock_verify.return_value = {
            "sub": test_username,
            "jti": test_jti,
            "type": "refresh",
            "pc": 0
        }
        
        with patch('app.api.auth.get_user_by_username_with_revocation_check', 
                   side_effect=mock_get_user_with_revocation_check):
            
            with patch('app.api.auth.RefreshTokenRequest') as mock_request_data:
                mock_request_data.return_value.refresh_token = test_refresh_token
                
                with patch('app.api.auth._set_refresh_cookie'):
                    with patch('app.api.auth.ensure_csrf_cookie'):
                        with patch('app.api.auth.create_access_token', 
                                   side_effect=lambda data: slow_token_creation(data, 0.01)):
                            with patch('app.api.auth.create_refresh_token', 
                                       side_effect=lambda data: slow_token_creation(data, 0.01)):
                                
                                # Call the optimized function
                                start_time = time.time()
                                result = await refresh_access_token(
                                    request=mock_request,
                                    response=mock_response,
                                    db=mock_db,
                                    refresh_data=None
                                )
                                end_time = time.time()
                                
                                # Verify tokens were created (should be ~0.01s total, not 0.02s)
                                assert len(token_creation_times) == 2
                                total_time = end_time - start_time
                                assert total_time < 0.015  # Should be less than sequential execution
                                
                                # Verify the result
                                assert isinstance(result, TokenResponse)
                                assert result.access_token == "token_new_jti"
                                assert result.refresh_token == "token_new_jti"


@pytest.mark.asyncio
async def test_refresh_access_token_revoked_token():
    """Test that revoked tokens are handled correctly."""
    mock_db = AsyncMock()
    mock_request = Request(scope={"type": "http", "method": "POST", "path": "/refresh"})
    mock_response = AsyncMock()
    
    test_username = "testuser"
    test_jti = "test_jti_123"
    test_refresh_token = create_refresh_token(
        data={"sub": test_username, "jti": test_jti, "type": "refresh", "pc": 0}
    )
    
    # Mock the function to return revoked token
    async def mock_get_user_with_revocation_check(db, username, jti):
        user = User(id=1, username=username, email="test@example.com", password_hash="hashed")
        return user, True  # Token is revoked
    
    with patch('app.api.auth.verify_token') as mock_verify:
        mock_verify.return_value = {
            "sub": test_username,
            "jti": test_jti,
            "type": "refresh",
            "pc": 0
        }
        
        with patch('app.api.auth.get_user_by_username_with_revocation_check', 
                   side_effect=mock_get_user_with_revocation_check):
            
            with patch('app.api.auth.RefreshTokenRequest') as mock_request_data:
                mock_request_data.return_value.refresh_token = test_refresh_token
                
                # Should raise HTTPException for revoked token
                from fastapi import HTTPException, status
                with pytest.raises(HTTPException) as exc_info:
                    await refresh_access_token(
                        request=mock_request,
                        response=mock_response,
                        db=mock_db,
                        refresh_data=None
                    )
                
                assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
                assert "Refresh token has been revoked" in exc_info.value.detail


@pytest.mark.asyncio 
async def test_database_query_optimization():
    """Test that database queries are optimized by using single query instead of multiple."""
    mock_db = AsyncMock()
    
    # Track database query calls
    query_calls = []
    
    async def mock_execute(query):
        query_calls.append(str(query))
        # Return empty result for simplicity
        from sqlalchemy import Result
        return Result([], lambda: None)
    
    mock_db.execute = mock_execute
    
    # Test the optimized function
    try:
        from app.repositories.revoked_token_repository import get_user_by_username_with_revocation_check
        await get_user_by_username_with_revocation_check(mock_db, "testuser", "test_jti")
    except Exception:
        pass  # We don't care about the actual result, just the query count
    
    # The optimized function should make only 1 query instead of 2
    # (original was: is_token_revoked + get_user_by_username = 2 queries)
    # (optimized: get_user_by_username_with_revocation_check = 1 query)
    assert len(query_calls) == 1
    
    # Verify it's a JOIN query, not separate queries
    query_str = query_calls[0]
    assert "JOIN" in query_str or "LEFT JOIN" in query_str or "outerjoin" in query_str.lower()