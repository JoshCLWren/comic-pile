"""Tests for the release-writer CLI validation and publishing logic."""

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import pytest

from scripts import release_writer


def _capture_stderr(func, *args, **kwargs) -> str:
    """Capture stderr from a function call that exits unsuccessfully."""
    f = io.StringIO()
    with redirect_stderr(f):
        try:
            func(*args, **kwargs)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            pytest.fail("Expected SystemExit with exit code 2")
    return f.getvalue()


def _capture_stdout(func, *args, **kwargs):
    """Capture stdout from a function call."""
    f = io.StringIO()
    with redirect_stdout(f):
        func(*args, **kwargs)
    return f.getvalue()


class TestReleaseWriterValidation:
    """Test release-writer input validation."""

    def test_publish_requires_valid_json(self) -> None:
        """Invalid JSON should be rejected.

        Args:
            None.

        Returns:
            None.
        """
        stderr = _capture_stderr(release_writer._validate_release, "not valid json")
        assert "invalid release JSON" in stderr

    def test_publish_requires_object(self) -> None:
        """Payload must be a JSON object.

        Args:
            None.

        Returns:
            None.
        """
        stderr = _capture_stderr(release_writer._validate_release, '"just a string"')
        assert "release payload must be an object" in stderr

    def test_publish_requires_all_fields(self) -> None:
        """All required fields must be present.

        Args:
            None.

        Returns:
            None.
        """
        payload = {"source_repository": "test/repo"}
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "missing release fields" in stderr

    def test_publish_rejects_unsupported_fields(self) -> None:
        """Unknown fields should be rejected.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["unknown_field"] = "value"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "unsupported fields" in stderr

    def test_publish_validates_source_repository(self) -> None:
        """source_repository must be 1-255 characters.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["source_repository"] = ""
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "source_repository must be 1..255 characters" in stderr

        payload["source_repository"] = "a" * 256
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "source_repository must be 1..255 characters" in stderr

    def test_publish_validates_source_pr_number(self) -> None:
        """source_pr_number must be positive integer.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["source_pr_number"] = 0
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "source_pr_number must be a positive integer" in stderr

        payload["source_pr_number"] = -1
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "source_pr_number must be a positive integer" in stderr

        payload["source_pr_number"] = "not a number"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "source_pr_number must be a positive integer" in stderr

    def test_publish_validates_source_merge_sha(self) -> None:
        """source_merge_sha must be 7-64 characters.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["source_merge_sha"] = "short"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "source_merge_sha must be 7..64 characters" in stderr

        payload["source_merge_sha"] = "a" * 65
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "source_merge_sha must be 7..64 characters" in stderr

    def test_publish_validates_timestamps(self) -> None:
        """Timestamps must be valid ISO-8601.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["merged_at"] = "not a timestamp"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "merged_at must be a valid ISO-8601 timestamp" in stderr

        payload["merged_at"] = "2024-01-01T00:00:00Z"
        payload["released_at"] = "invalid"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "released_at must be a valid ISO-8601 timestamp" in stderr

    def test_publish_validates_string_fields(self) -> None:
        """String fields must be non-empty and within length limits.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["category"] = ""
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "category must be non-empty" in stderr

        payload["category"] = "a" * 101
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "category must be non-empty and at most 100 characters" in stderr

        payload["category"] = "Valid"
        payload["title"] = ""
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "title must be non-empty" in stderr

        payload["title"] = "Valid"
        payload["summary"] = ""
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "summary must be non-empty" in stderr

        payload["summary"] = "a" * 1201
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "summary must be non-empty and at most 1200 characters" in stderr

    def test_publish_validates_body(self) -> None:
        """Body must be null or <= 6000 characters.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["body"] = "a" * 6001
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "body must be null or at most 6000 characters" in stderr

    def test_publish_validates_visibility(self) -> None:
        """Visibility must be public or internal.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["visibility"] = "private"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "unsupported visibility" in stderr

    def test_publish_validates_status(self) -> None:
        """Status must be draft, published, or retracted.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["status"] = "archived"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "unsupported status" in stderr

    def test_publish_validates_provenance_json(self) -> None:
        """provenance_json must be an object.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        payload["provenance_json"] = "not an object"
        stderr = _capture_stderr(release_writer._validate_release, json.dumps(payload))
        assert "provenance_json must be an object" in stderr

    def test_publish_accepts_valid_payload(self) -> None:
        """A fully valid payload should pass validation and return normalized payload.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        result = release_writer._validate_release(json.dumps(payload))
        assert result["source_repository"] == "JoshCLWren/comic-pile"
        assert result["source_pr_number"] == 123
        assert result["source_merge_sha"] == "abcdef1234567890"
        assert result["visibility"] == "public"
        assert result["status"] == "published"
        assert result["sort_order"] == 0
        assert result["provenance_json"] == {"source": "github"}

    def test_publish_sets_defaults(self) -> None:
        """Optional fields should get default values.

        Args:
            None.

        Returns:
            None.
        """
        payload = _valid_payload()
        # Remove optional fields
        for field in ("body", "visibility", "status", "sort_order", "provenance_json"):
            del payload[field]

        result = release_writer._validate_release(json.dumps(payload))
        assert result["visibility"] == "public"
        assert result["status"] == "published"
        assert result["sort_order"] == 0
        assert result["provenance_json"] == {}


class TestReleaseWriterCheck:
    """Test the check command for reconciliation."""

    def test_check_validates_pr_number(self) -> None:
        """PR number must be an integer.

        Args:
            None.

        Returns:
            None.
        """
        with patch.object(release_writer, "_request") as mock_request:
            mock_request.return_value = {"exists": False, "release": None}
            stderr = _capture_stderr(release_writer._check, "repo", "not-a-number", "abcdef1234567890")
            assert "PR number must be an integer" in stderr

    def test_check_calls_api(self) -> None:
        """Check should call the reconciliation endpoint.

        Args:
            None.

        Returns:
            None.
        """
        with patch.object(release_writer, "_request") as mock_request:
            mock_request.return_value = {"exists": True, "release": {"id": 42}}
            with patch.object(release_writer, "_api_base", return_value="http://test/api"):
                with patch.object(release_writer, "_token", return_value="test-token"):
                    release_writer._check("JoshCLWren/comic-pile", "123", "abcdef1234567890")
            mock_request.assert_called_once()
            args, kwargs = mock_request.call_args
            assert args[0] == "GET"
            assert "source_repository=JoshCLWren%2Fcomic-pile" in args[1]
            assert "source_pr_number=123" in args[1]
            assert "source_merge_sha=abcdef1234567890" in args[1]


class TestReleaseWriterSkip:
    """Test the skip command for internal changes."""

    def test_skip_requires_fields(self) -> None:
        """Skip payload needs required fields.

        Args:
            None.

        Returns:
            None.
        """
        payload = {"source_repository": "test/repo"}
        stderr = _capture_stderr(release_writer._skip, json.dumps(payload))
        assert "skip payload is missing required fields" in stderr

    def test_skip_validates_timestamp(self) -> None:
        """Skip requires valid merged_at timestamp.

        Args:
            None.

        Returns:
            None.
        """
        payload = {
            "source_repository": "test/repo",
            "source_pr_number": 1,
            "source_merge_sha": "abcdef1234567890",
            "merged_at": "invalid",
            "reason": "test",
        }
        stderr = _capture_stderr(release_writer._skip, json.dumps(payload))
        assert "merged_at must be a valid ISO-8601 timestamp" in stderr

    def test_skip_validates_reason(self) -> None:
        """Skip requires non-empty reason <= 500 chars.

        Args:
            None.

        Returns:
            None.
        """
        payload = {
            "source_repository": "test/repo",
            "source_pr_number": 1,
            "source_merge_sha": "abcdef1234567890",
            "merged_at": "2024-01-01T00:00:00Z",
            "reason": "",
        }
        stderr = _capture_stderr(release_writer._skip, json.dumps(payload))
        assert "skip reason must be non-empty" in stderr

        payload["reason"] = "a" * 501
        stderr = _capture_stderr(release_writer._skip, json.dumps(payload))
        assert "skip reason must be non-empty and at most 500 characters" in stderr

    def test_skip_outputs_classification(self) -> None:
        """Skip should output machine-readable classification.

        Args:
            None.

        Returns:
            None.
        """
        payload = {
            "source_repository": "test/repo",
            "source_pr_number": 1,
            "source_merge_sha": "abcdef1234567890",
            "merged_at": "2024-01-01T00:00:00Z",
            "reason": "Internal maintenance only",
        }
        output = _capture_stdout(release_writer._skip, json.dumps(payload))
        result = json.loads(output.strip())
        assert result["classification"] == "internal"
        assert result["skipped"] is True
        assert result["reason"] == "Internal maintenance only"
        assert result["source_pr_number"] == 1


class TestReleaseWriterRequest:
    """Test the _request function."""

    def test_request_builds_correct_headers(self) -> None:
        """Request should include the auth token in headers.

        Args:
            None.

        Returns:
            None.
        """
        with patch("scripts.release_writer.urllib.request.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = json.dumps({"id": 1}).encode()
            mock_response.__enter__ = Mock(return_value=mock_response)
            mock_response.__exit__ = Mock(return_value=False)
            mock_urlopen.return_value = mock_response

            with patch.object(release_writer, "_api_base", return_value="http://test/api"):
                with patch.object(release_writer, "_token", return_value="secret-token"):
                    release_writer._request("PUT", "http://test/api/", {"test": "data"})

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.get_method() == "PUT"
            assert request.get_header("X-release-writer-token") == "secret-token"
            assert request.get_header("Content-type") == "application/json"
            assert "secret-token" not in request.full_url
            assert "secret-token" not in request.data.decode()

    def test_request_handles_http_error(self) -> None:
        """HTTP errors should be caught and formatted.

        Args:
            None.

        Returns:
            None.
        """
        import urllib.error

        with patch("scripts.release_writer.urllib.request.urlopen") as mock_urlopen:
            http_error = urllib.error.HTTPError(
                url="http://test/api/",
                code=409,
                msg="Conflict",
                hdrs={},
                fp=io.BytesIO(b'{"detail": "Source conflict"}'),
            )
            mock_urlopen.side_effect = http_error

            with patch.object(release_writer, "_api_base", return_value="http://test/api"):
                with patch.object(release_writer, "_token", return_value="secret-token"):
                    stderr = _capture_stderr(release_writer._request, "PUT", "http://test/api/", {"test": "data"})
            assert "release API returned HTTP 409" in stderr

    def test_request_handles_url_error(self) -> None:
        """URL errors (connection refused, etc.) should be caught.

        Args:
            None.

        Returns:
            None.
        """
        import urllib.error

        with patch("scripts.release_writer.urllib.request.urlopen") as mock_urlopen:
            url_error = urllib.error.URLError(reason="Connection refused")
            mock_urlopen.side_effect = url_error

            with patch.object(release_writer, "_api_base", return_value="http://test/api"):
                with patch.object(release_writer, "_token", return_value="secret-token"):
                    stderr = _capture_stderr(release_writer._request, "PUT", "http://test/api/", {"test": "data"})
            assert "release API request failed: Connection refused" in stderr


class TestReleaseWriterEnvironment:
    """Test environment variable handling."""

    def test_missing_api_url(self) -> None:
        """Missing RELEASE_API_URL should fail.

        Args:
            None.

        Returns:
            None.
        """
        with patch.dict(os.environ, {"RELEASE_API_URL": "", "RELEASE_WRITER_TOKEN": "token"}, clear=True):
            stderr = _capture_stderr(release_writer._api_base)
            assert "RELEASE_API_URL is required" in stderr

    def test_missing_token(self) -> None:
        """Missing RELEASE_WRITER_TOKEN should fail.

        Args:
            None.

        Returns:
            None.
        """
        with patch.dict(os.environ, {"RELEASE_API_URL": "http://test/api", "RELEASE_WRITER_TOKEN": ""}, clear=True):
            stderr = _capture_stderr(release_writer._token)
            assert "RELEASE_WRITER_TOKEN is required" in stderr


def _valid_payload() -> dict:
    """Return a valid release payload for testing."""
    return {
        "source_repository": "JoshCLWren/comic-pile",
        "source_pr_number": 123,
        "source_merge_sha": "abcdef1234567890",
        "merged_at": "2024-01-01T00:00:00Z",
        "released_at": "2024-01-01T00:00:00Z",
        "category": "What's New",
        "title": "Test Release",
        "summary": "A test release summary",
        "body": "More details here",
        "visibility": "public",
        "status": "published",
        "sort_order": 0,
        "provenance_json": {"source": "github"},
    }
