"""Regression coverage for safe ComicVine fallback diagnostics (#4516)."""

from __future__ import annotations

import logging

import pytest

from app.services import comicvine_fallback


@pytest.mark.asyncio
async def test_inline_typeerror_reports_source_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not print provider exception text, raw URLs, or credentials."""

    async def fail_hydration(_identity_id: int) -> bool:
        raise TypeError("api_key=secret-value https://provider.invalid/private")

    monkeypatch.setattr(comicvine_fallback, "_run_issue_hydration", fail_hydration)

    with caplog.at_level(logging.WARNING, logger=comicvine_fallback.__name__):
        succeeded = await comicvine_fallback.refresh_issue_metadata(2656)

    assert succeeded is False
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "comicvine_fallback_inline_failed identity_id=2656" in message
        and "error=TypeError" in message
        and "source=" in message
        for message in messages
    )
    assert all("secret-value" not in message for message in messages)
    assert all("provider.invalid" not in message for message in messages)
