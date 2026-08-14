"""Focused tests for the release-writer command helper."""

import json

from scripts import release_writer


def test_recent_filters_unmerged_and_sorts_by_exact_merge_time(monkeypatch, capsys):
    """Recent reconciliation should use merged_at, not API response order."""
    page = [
        {
            "number": 10,
            "merged_at": "2026-08-12T10:00:00Z",
            "merge_commit_sha": "a" * 40,
            "title": "Older merge",
        },
        {
            "number": 99,
            "merged_at": None,
            "merge_commit_sha": None,
            "title": "Closed without merge",
        },
        {
            "number": 12,
            "merged_at": "2026-08-14T01:00:00Z",
            "merge_commit_sha": "c" * 40,
            "title": "Newest merge",
        },
        {
            "number": 11,
            "merged_at": "2026-08-13T10:00:00Z",
            "merge_commit_sha": "b" * 40,
            "title": "Middle merge",
        },
    ]
    seen_urls: list[str] = []

    def fake_github_request(url: str):
        seen_urls.append(url)
        return page

    monkeypatch.setattr(release_writer, "_github_request", fake_github_request)

    release_writer._recent("JoshCLWren/comic-pile", "2")

    result = json.loads(capsys.readouterr().out)
    assert [item["number"] for item in result] == [12, 11]
    assert len(seen_urls) == 1
    assert "state=closed" in seen_urls[0]
    assert "base=main" in seen_urls[0]


def test_recent_paginates_until_all_closed_prs_are_seen(monkeypatch, capsys):
    """Late pages can contain a newer merge than rows from the first page."""
    first_page = [
        {
            "number": number,
            "merged_at": "2026-01-01T00:00:00Z",
            "merge_commit_sha": f"{number:040d}",
            "title": f"PR {number}",
        }
        for number in range(1, 101)
    ]
    second_page = [
        {
            "number": 101,
            "merged_at": "2026-08-14T01:00:00Z",
            "merge_commit_sha": "f" * 40,
            "title": "Late-page recent merge",
        }
    ]

    def fake_github_request(url: str):
        return second_page if "page=2" in url else first_page

    monkeypatch.setattr(release_writer, "_github_request", fake_github_request)

    release_writer._recent("JoshCLWren/comic-pile", "1")

    result = json.loads(capsys.readouterr().out)
    assert result[0]["number"] == 101


def test_skip_records_hidden_internal_release(monkeypatch, capsys):
    """Internal classifications should become durable without appearing publicly."""
    monkeypatch.setenv("RELEASE_API_URL", "https://example.test/api/v1/releases")
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(method: str, url: str, payload: dict[str, object] | None = None):
        requests.append((method, url, payload))
        return {"id": 42, "visibility": "internal"}

    monkeypatch.setattr(release_writer, "_request", fake_request)

    release_writer._skip(
        json.dumps(
            {
                "source_repository": "JoshCLWren/comic-pile",
                "source_pr_number": 1177,
                "source_merge_sha": "d" * 40,
                "merged_at": "2026-08-14T01:00:00Z",
                "reason": "Factory-only maintenance with no user-facing product change.",
            }
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["recorded"] is True
    assert output["skipped"] is True
    assert requests[0][0] == "PUT"
    assert requests[0][1] == "https://example.test/api/v1/releases/"
    payload = requests[0][2]
    assert payload is not None
    assert payload["visibility"] == "internal"
    assert payload["status"] == "published"
    assert payload["source_pr_number"] == 1177
    assert payload["released_at"] == "2026-08-14T01:00:00Z"
