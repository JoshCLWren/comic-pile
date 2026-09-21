"""Tests for ComicVine URL parsing used by the direct-link correction flow."""

from __future__ import annotations

from app.services.comicvine_url import looks_like_url, parse_comicvine_url


def test_parses_issue_url() -> None:
    parsed = parse_comicvine_url(
        "https://comicvine.gamespot.com/superman-34-i-superman/4000-1154070/"
    )
    assert parsed is not None
    assert parsed.kind == "issue"
    assert parsed.resource_id == 1154070


def test_parses_volume_url() -> None:
    parsed = parse_comicvine_url("https://comicvine.gamespot.com/superman/4050-148476/")
    assert parsed is not None
    assert parsed.kind == "volume"
    assert parsed.resource_id == 148476


def test_parses_http_scheme_and_query_string() -> None:
    parsed = parse_comicvine_url(
        "http://comicvine.gamespot.com/superman/4050-148476/?foo=bar#frag"
    )
    assert parsed is not None
    assert parsed.kind == "volume"
    assert parsed.resource_id == 148476


def test_www_host_is_accepted() -> None:
    parsed = parse_comicvine_url("https://www.comicvine.gamespot.com/x/4000-11/")
    assert parsed is not None
    assert parsed.kind == "issue"
    assert parsed.resource_id == 11


def test_trailing_missing_slash_ok() -> None:
    parsed = parse_comicvine_url("https://comicvine.gamespot.com/superman/4050-148476")
    assert parsed is not None
    assert parsed.kind == "volume"
    assert parsed.resource_id == 148476


def test_rejects_unknown_host() -> None:
    assert parse_comicvine_url("https://comicvine.example.com/superman/4050-148476/") is None
    assert parse_comicvine_url("https://github.com/superman/4000-1154070/") is None


def test_rejects_unsupported_resource_prefix() -> None:
    assert parse_comicvine_url("https://comicvine.gamespot.com/arc/4045-12345/") is None


def test_rejects_garbage() -> None:
    assert parse_comicvine_url("not a url at all") is None
    assert parse_comicvine_url("") is None
    assert parse_comicvine_url("https://comicvine.gamespot.com/") is None
    assert parse_comicvine_url("comicvine.gamespot.com") is None


def test_rejects_non_http_scheme() -> None:
    assert (
        parse_comicvine_url("ftp://comicvine.gamespot.com/superman/4050-148476/") is None
    )


def test_looks_like_url_classification() -> None:
    assert looks_like_url("https://comicvine.gamespot.com/x/4000-1/") is True
    assert looks_like_url("http://example.com/x") is True
    assert looks_like_url("Superman") is False
    assert looks_like_url("") is False