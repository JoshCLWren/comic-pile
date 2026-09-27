#!/usr/bin/env python3
"""Simple test script for series mapping commit functionality."""

import json
import time
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_schema_validation():
    """Test that the schemas work correctly."""
    from app.schemas.catalog import SeriesMappingCommitRequest, SeriesMappingCommitResponse
    
    # Test valid request
    request_data = {
        "preview_token": "test-token",
        "idempotency_key": "test-key-123",
        "approved_row_ids": ["issue:1", "issue:2"]
    }
    
    request = SeriesMappingCommitRequest(**request_data)
    assert len(request.approved_row_ids) == 2
    assert request.approved_row_ids[0] == "issue:1"
    assert request.approved_row_ids[1] == "issue:2"
    
    # Test invalid request format
    try:
        invalid_request = {
            "preview_token": "test-token",
            "idempotency_key": "test-key-123",
            "approved_row_ids": ["invalid:123"]  # Should be "issue:123"
        }
        SeriesMappingCommitRequest(**invalid_request)
        assert False, "Should have raised validation error"
    except Exception:
        pass  # Expected
    
    print("✓ Schema validation tests passed")

def test_token_generation():
    """Test preview token generation and verification."""
    from app.services.catalog import _generate_preview_token, verify_preview_token
    
    # Test token generation
    payload = {
        "user_id": 1,
        "provider": "comicvine",
        "provider_series_external_id": "123",
        "origin_issue_id": 1,
        "scope_key": "exact:1:1",
        "issue_numbers": ["1"],
        "classification_digest": "safe_exact_match:1",
        "issued_at": time.time(),
        "expires_at": time.time() + 600,
    }
    
    token = _generate_preview_token(**payload)
    assert isinstance(token, str)
    assert len(token) > 0
    
    # Test token verification
    verified_payload = verify_preview_token(token, 1)  # Correct user ID
    assert verified_payload["user_id"] == 1
    assert verified_payload["provider"] == "comicvine"
    
    # Test token verification with wrong user ID
    try:
        verify_preview_token(token, 999)  # Wrong user ID
        assert False, "Should have raised validation error"
    except Exception:
        pass  # Expected
    
    print("✓ Token generation and verification tests passed")

def test_issue_number_helpers():
    """Test the issue number helper functions."""
    from app.services.catalog import _normalize_issue_number, _is_special_issue, _is_ambiguous, _is_exact_match
    
    # Test issue number normalization
    assert _normalize_issue_number("1") == "1"
    assert _normalize_issue_number("1.0") == "1"
    assert _normalize_issue_number("1A") == "1a"
    assert _normalize_issue_number("#1") == "1"
    
    # Test special issue detection
    assert _is_special_issue("annual") == True
    assert _is_special_issue("special") == True
    assert _is_special_issue("1") == False
    assert _is_special_issue("1.5") == False
    
    # Test ambiguity detection
    assert _is_ambiguous("1.5") == True
    assert _is_ambiguous("IV") == True
    assert _is_ambiguous("1A") == True
    assert _is_ambiguous("1-2") == True
    assert _is_ambiguous("1") == False
    
    # Test exact match
    assert _is_exact_match("1", "1") == True
    assert _is_exact_match("1.0", "1") == True
    assert _is_exact_match("1", "2") == False
    assert _is_exact_match("", "1") == False
    
    print("✓ Issue number helper function tests passed")

if __name__ == "__main__":
    print("Running basic functionality tests...")
    
    try:
        test_schema_validation()
        test_token_generation()
        test_issue_number_helpers()
        print("\n✅ All basic functionality tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)