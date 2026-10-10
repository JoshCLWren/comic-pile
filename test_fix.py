#!/usr/bin/env python3
"""Manual test script to verify the sanitize_evidence_text fix."""

import sys
import os
sys.path.append('app')

from services.performance_issue_service import sanitize_evidence_text, build_issue_body

def test_sanitize_evidence_text():
    """Test the sanitize_evidence_text function."""
    print("Testing sanitize_evidence_text...")
    
    # Test cases from the failing tests
    test_cases = [
        ("authorization: Bearer abc123", "authorization: [REDACTED]"),
        ("cookie: session=xyz", "cookie: [REDACTED]"),
        ("GET /api/v1/creators", "GET /api/v1/creators"),
        ("api-key: abc123def", "api-key: [REDACTED]"),
        ("access_token=secret123", "access_token=[REDACTED]"),
        ("password=mypassword", "password=[REDACTED]"),
    ]
    
    all_passed = True
    for input_text, expected in test_cases:
        result = sanitize_evidence_text(input_text)
        if result == expected:
            print(f"✅ '{input_text}' -> '{result}'")
        else:
            print(f"❌ '{input_text}' -> '{result}' (expected: '{expected}')")
            all_passed = False
    
    return all_passed

def test_secret_redaction():
    """Test the secret redaction in build_issue_body."""
    print("\nTesting secret redaction in build_issue_body...")
    
    # Test case from the failing test
    body = build_issue_body(
        kind="request",
        fingerprint="abc123",
        canonical="request|GET|/x|warm|unknown|mixed",
        method="GET",
        route_template="/x",
        duration_ms=1500.0,
        threshold_ms=1000.0,
        event_label="violation",
        server_timing="app;dur=1500.00",
        deployment_id="dpl_1",
        request_ids=["authorization: Bearer super-secret-token"],
    )
    
    if "super-secret-token" not in body and "[REDACTED]" in body:
        print("✅ Secret redaction test PASSED")
        print(f"Body contains [REDACTED]: { '[REDACTED]' in body}")
        print(f"Body does NOT contain super-secret-token: { 'super-secret-token' not in body}")
        return True
    else:
        print("❌ Secret redaction test FAILED")
        print(f"Body: {body}")
        print(f"Contains super-secret-token: { 'super-secret-token' in body}")
        print(f"Contains [REDACTED]: { '[REDACTED]' in body}")
        return False

if __name__ == "__main__":
    print("Running manual tests for performance issue service fix...")
    
    test1_passed = test_sanitize_evidence_text()
    test2_passed = test_secret_redaction()
    
    if test1_passed and test2_passed:
        print("\n🎉 All tests PASSED! The fix is working correctly.")
        sys.exit(0)
    else:
        print("\n❌ Some tests FAILED.")
        sys.exit(1)