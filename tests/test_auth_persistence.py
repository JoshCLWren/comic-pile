"""Regression coverage for browser authentication persistence."""


from app.auth import REFRESH_TOKEN_EXPIRE_DAYS, refresh_cookie_max_age_seconds


def test_refresh_cookie_max_age_matches_refresh_jwt_lifetime() -> None:
    """Refresh cookie lifetime must follow REFRESH_TOKEN_EXPIRE_DAYS, not a hard-coded 30d."""
    assert refresh_cookie_max_age_seconds() == REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    assert refresh_cookie_max_age_seconds() != 60 * 60 * 24 * 30
