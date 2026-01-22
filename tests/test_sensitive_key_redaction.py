"""Test for recursive sensitive key redaction."""

from app.main import contains_sensitive_keys


def test_top_level_password():
    """Test top-level password detection."""
    assert contains_sensitive_keys({"password": "secret123"}) is True


def test_nested_password():
    """Test nested password detection."""
    assert contains_sensitive_keys({"user": {"password": "secret123"}}) is True


def test_deeply_nested_password():
    """Test deeply nested password detection."""
    assert (
        contains_sensitive_keys({"level1": {"level2": {"level3": {"password": "secret123"}}}})
        is True
    )


def test_nested_in_list():
    """Test password nested inside a list."""
    assert contains_sensitive_keys({"users": [{"password": "secret123"}, {"name": "test"}]}) is True


def test_deeply_nested_in_list():
    """Test password nested deep in a list."""
    assert contains_sensitive_keys({"data": [{"items": [{"config": {"secret": "value"}}]}]}) is True


def test_no_sensitive_keys():
    """Test detection when no sensitive keys present."""
    assert contains_sensitive_keys({"name": "test", "value": 123}) is False


def test_nested_no_sensitive_keys():
    """Test detection when no sensitive keys in nested structure."""
    assert contains_sensitive_keys({"user": {"name": "test", "data": {"value": 123}}}) is False


def test_token_variants():
    """Test various token key names."""
    assert contains_sensitive_keys({"access_token": "abc123"}) is True
    assert contains_sensitive_keys({"refresh_token": "xyz789"}) is True
    assert contains_sensitive_keys({"api_key": "key123"}) is True


def test_nested_token_variants():
    """Test nested token variants."""
    assert contains_sensitive_keys({"auth": {"access_token": "abc123"}}) is True
    assert contains_sensitive_keys({"config": {"nested": {"refresh_token": "xyz"}}}) is True
    assert contains_sensitive_keys({"settings": [{"api_key": "key"}]}) is True


def test_mixed_nested_structure():
    """Test mixed nested structure with some sensitive and some not."""
    assert (
        contains_sensitive_keys({"user": {"name": "test", "auth": {"password": "secret"}}}) is True
    )
    assert contains_sensitive_keys({"data": [{"items": [{"id": 1}, {"secret": "value"}]}]}) is True
