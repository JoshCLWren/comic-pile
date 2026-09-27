#!/usr/bin/env python3
"""Standalone test for series mapping commit functionality."""

import json
import hashlib
import hmac
import time
import re
from typing import Dict, Any, List

def normalize_issue_number(value: str) -> str:
    """Normalize an issue number for exact comparison."""
    normalized = re.sub(r"[^0-9.]", "", value.lower().strip())
    normalized = normalized.strip(".")
    return normalized

def is_special_issue(issue_number: str) -> bool:
    """Check if issue number indicates a special/annual issue."""
    stripped = issue_number.strip().lower()
    if not stripped:
        return True
    # Roman numerals are not special issues - they are ambiguous numbering
    if re.fullmatch(r"[ivx]+", stripped):
        return False
    # Purely non-numeric or annual/special keywords
    if re.search(r"\b(annual|special|hc|tpb|gn|omnibus|deluxe|absolute|hardcover|trade paperback|graphic novel)\b", stripped):
        return True
    if re.fullmatch(r"[^0-9]*", stripped):
        return True
    if re.search(r"\.[^0-9]+$", stripped):
        return True
    return False

def is_exact_match(issue_number: str, origin_issue_number: str) -> bool:
    """Check if issue number exactly matches the origin issue number."""
    if not issue_number or not origin_issue_number:
        return False
    return normalize_issue_number(issue_number) == normalize_issue_number(origin_issue_number)

def is_conflicting_mapping(issue_info: Dict[str, Any], provider: str) -> bool:
    """Check if issue has a confirmed mapping that conflicts with the selected series."""
    if issue_info.get("current_mapping_status") != "confirmed":
        return False
    issue_provider = issue_info.get("provider")
    # If provider differs, it's a conflict (cross-provider mapping conflict)
    if issue_provider != provider:
        return True
    # Same provider: we cannot reliably determine series-level conflict without
    # additional data (issue's volume/series not stored locally). Defer to review.
    return False

def is_ambiguous(issue_number: str) -> bool:
    """Check if issue number is ambiguous."""
    # Fractional, roman, suffixed, or named numbering is never bulk-safe.
    ambiguous_patterns = [
        r"\d+\.\d+",  # Fractional numbers (e.g., "1.5", "0.5")
        r"^[ivx]+$",  # Roman numerals
        r"^[a-z]+$",  # Letters only
        r"\.\d+$",  # Decimal suffixes
        r"\d+[a-zA-Z]",  # Named variants like "1A", "2B"
        r"\d+\s*-\s*\d+",  # Ranges like "1-2"
        r"#",  # Hash-prefixed like "#1"
    ]

    issue_number_lower = issue_number.lower()
    for pattern in ambiguous_patterns:
        if re.search(pattern, issue_number_lower):
            return True
    return False

def generate_preview_token(
    user_id: int,
    provider: str,
    provider_series_external_id: str,
    origin_issue_id: int,
    scope_key: str,
    issued_at: float,
    expires_at: float,
    issue_numbers: List[str] | None = None,
    classification_digest: str | None = None,
) -> str:
    """Generate an HMAC-signed preview token."""
    # Use a simple secret key for testing
    secret_key = "test-secret-key"
    
    # Create token payload
    payload = {
        "user_id": user_id,
        "provider": provider,
        "provider_series_external_id": provider_series_external_id,
        "origin_issue_id": origin_issue_id,
        "scope_key": scope_key,
        "issue_numbers": issue_numbers or [],
        "classification_digest": classification_digest or "",
        "issued_at": issued_at,
        "expires_at": expires_at,
    }

    # Generate signature
    payload_json = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Combine payload and signature
    token_data = {
        "payload": payload,
        "signature": signature,
    }

    return json.dumps(token_data)

def verify_preview_token(token: str, expected_user_id: int) -> Dict[str, Any]:
    """Verify an HMAC-signed preview token and check expiry and ownership."""
    secret_key = "test-secret-key"
    
    try:
        token_data = json.loads(token)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid_preview_token") from exc

    payload = token_data.get("payload") if isinstance(token_data, dict) else None
    signature = token_data.get("signature") if isinstance(token_data, dict) else None
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise ValueError("invalid_preview_token")

    payload_json = json.dumps(payload, sort_keys=True)
    expected_sig = hmac.new(
        secret_key.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        raise ValueError("invalid_preview_token")

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)) or float(expires_at) <= time.time():
        raise ValueError("preview_token_expired")

    payload_user = payload.get("user_id")
    if payload_user != expected_user_id:
        raise ValueError("invalid_preview_token")

    return payload

def test_schema_validation():
    """Test basic schema-like validation."""
    from pydantic import BaseModel, Field, field_validator
    
    class TestCommitRequest(BaseModel):
        preview_token: str = Field(..., min_length=1, description="Signed preview token")
        idempotency_key: str = Field(..., min_length=1, description="Unique key for idempotent commits")
        approved_row_ids: List[str] = Field(..., description="List of approved row IDs")

        @field_validator("approved_row_ids")
        @classmethod
        def validate_approved_row_ids(cls, approved_row_ids: List[str]) -> List[str]:
            """Validate that all approved row IDs are properly formatted."""
            for row_id in approved_row_ids:
                if not row_id.startswith("issue:"):
                    raise ValueError(f"invalid row_id format: {row_id} - must start with 'issue:'")
                try:
                    int(row_id[6:])  # Extract and validate issue number part
                except ValueError:
                    raise ValueError(f"invalid row_id format: {row_id} - issue number must be integer")
            return approved_row_ids
    
    # Test valid request
    request_data = {
        "preview_token": "test-token",
        "idempotency_key": "test-key-123",
        "approved_row_ids": ["issue:1", "issue:2"]
    }
    
    request = TestCommitRequest(**request_data)
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
        TestCommitRequest(**invalid_request)
        assert False, "Should have raised validation error"
    except Exception:
        pass  # Expected
    
    print("✓ Schema validation tests passed")

def test_token_generation():
    """Test preview token generation and verification."""
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
    
    token = generate_preview_token(**payload)
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
    except ValueError:
        pass  # Expected
    
    # Test expired token
    expired_payload = payload.copy()
    expired_payload["expires_at"] = time.time() - 1  # 1 second ago
    expired_token = generate_preview_token(**expired_payload)
    
    try:
        verify_preview_token(expired_token, 1)
        assert False, "Should have raised validation error for expired token"
    except ValueError as e:
        assert "preview_token_expired" in str(e)
    
    print("✓ Token generation and verification tests passed")

def test_issue_number_helpers():
    """Test the issue number helper functions."""
    # Test issue number normalization
    assert normalize_issue_number("1") == "1"
    assert normalize_issue_number("1.0") == "1"
    assert normalize_issue_number("1A") == "1"
    assert normalize_issue_number("#1") == "1"
    
    # Test special issue detection
    assert is_special_issue("annual") == True
    assert is_special_issue("special") == True
    assert is_special_issue("1") == False
    assert is_special_issue("1.5") == False
    
    # Test ambiguity detection
    assert is_ambiguous("1.5") == True
    assert is_ambiguous("IV") == True
    assert is_ambiguous("1A") == True
    assert is_ambiguous("1-2") == True
    assert is_ambiguous("1") == False
    
    # Test exact match
    assert is_exact_match("1", "1") == True
    assert is_exact_match("1.0", "1") == True
    assert is_exact_match("1", "2") == False
    assert is_exact_match("", "1") == False
    
    print("✓ Issue number helper function tests passed")

def test_classification_logic():
    """Test the issue classification logic."""
    # Test data
    issues = [
        {"issue_id": 1, "issue_number": "1", "current_mapping_status": None},
        {"issue_id": 2, "issue_number": "2", "current_mapping_status": "confirmed"},
        {"issue_id": 3, "issue_number": "1.5", "current_mapping_status": None},
        {"issue_id": 4, "issue_number": "annual", "current_mapping_status": None},
        {"issue_id": 5, "issue_number": "IV", "current_mapping_status": None},
        {"issue_id": 6, "issue_number": "1A", "current_mapping_status": None},
        {"issue_id": 7, "issue_number": "1-2", "current_mapping_status": None},
    ]
    
    origin_issue_number = "1"
    provider = "comicvine"
    
    counts = {
        "already_confirmed": 0,
        "safe_exact_match": 0,
        "needs_review_ambiguous": 0,
        "needs_review_conflict": 0,
        "unresolved": 0,
        "excluded_special": 0,
    }
    
    classified_issues = []
    
    for issue in issues:
        issue_number = issue["issue_number"]
        
        if is_special_issue(issue_number):
            classification = "excluded_special"
            counts["excluded_special"] += 1
        elif is_conflicting_mapping(issue, provider):
            classification = "needs_review_conflict"
            counts["needs_review_conflict"] += 1
        elif is_ambiguous(issue_number):
            classification = "needs_review_ambiguous"
            counts["needs_review_ambiguous"] += 1
        elif issue["current_mapping_status"] == "confirmed":
            classification = "already_confirmed"
            counts["already_confirmed"] += 1
        elif is_exact_match(issue_number, origin_issue_number):
            classification = "safe_exact_match"
            counts["safe_exact_match"] += 1
        else:
            classification = "unresolved"
            counts["unresolved"] += 1
        
        issue["classification"] = classification
        issue["proposed_mapping"] = classification in ["safe_exact_match", "already_confirmed"]
        classified_issues.append(issue)
    
    # Verify expected classifications
    assert classified_issues[0]["classification"] == "safe_exact_match"  # "1" matches origin "1"
    assert classified_issues[1]["classification"] == "already_confirmed"  # Already confirmed
    assert classified_issues[2]["classification"] == "needs_review_ambiguous"  # "1.5" is fractional
    assert classified_issues[3]["classification"] == "excluded_special"  # "annual" is special
    assert classified_issues[4]["classification"] == "needs_review_ambiguous"  # "IV" is roman numeral
    assert classified_issues[5]["classification"] == "needs_review_ambiguous"  # "1A" is suffixed
    assert classified_issues[6]["classification"] == "needs_review_ambiguous"  # "1-2" is range
    
    print("✓ Classification logic tests passed")

if __name__ == "__main__":
    print("Running basic functionality tests...")
    
    try:
        test_schema_validation()
        test_token_generation()
        test_issue_number_helpers()
        test_classification_logic()
        print("\n✅ All basic functionality tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)