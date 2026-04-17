"""Tests for scripts/comic_pile_api.py verify_reading_order() and create_wildstorm_reading_order.py flags."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _load_script_module(name: str) -> ModuleType:
    """Dynamically load a module from the scripts directory."""
    spec = importlib.util.spec_from_file_location(
        name,
        str(Path(__file__).parent.parent / "scripts" / f"{name}.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_comic_pile_api = _load_script_module("comic_pile_api")
sys.modules["comic_pile_api"] = _comic_pile_api
DepEdge = _comic_pile_api.DepEdge
verify_reading_order = _comic_pile_api.verify_reading_order

_wildstorm_chains = _load_script_module("wildstorm_chains")
sys.modules["wildstorm_chains"] = _wildstorm_chains

_create_module = _load_script_module("create_wildstorm_reading_order")
run_verify = _create_module.run_verify
run_fix = _create_module.run_fix
_parse_args = _create_module._parse_args


def _mock_response(json_data: dict | list, status_code: int = 200) -> MagicMock:
    """Create a mock requests response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()
    return mock


def _make_get_handler(
    threads: dict[str, dict],
    issues: dict[int, list[dict]],
    deps: dict[int, dict],
) -> MagicMock:
    """Create a mock requests.get that routes responses by URL pattern."""

    def _get(url: str, **kwargs: object) -> MagicMock:
        if "/api/threads/" in url and "/v1/" not in url:
            return _mock_response(list(threads.values()))
        if "/issues" in url and "dependencies" not in url:
            for thread_id_str, thread_issues in issues.items():
                if f"/{thread_id_str}/issues" in url:
                    return _mock_response({"issues": thread_issues})
            return _mock_response({"issues": []})
        if "/dependencies" in url:
            for thread_id_str, dep_data in deps.items():
                if f"/{thread_id_str}/dependencies" in url:
                    return _mock_response(dep_data)
            return _mock_response({"blocking": [], "blocked_by": []})
        return _mock_response({})

    return MagicMock(side_effect=_get)


THREADS = {
    "Stormwatch Vol. 1": {"id": 1, "title": "Stormwatch Vol. 1"},
    "Stormwatch Vol. 2": {"id": 2, "title": "Stormwatch Vol. 2"},
    "WildC.A.T.s/Aliens": {"id": 3, "title": "WildC.A.T.s/Aliens"},
}

ISSUES = {
    1: [
        {"id": 101, "issue_number": "37"},
        {"id": 102, "issue_number": "43"},
        {"id": 103, "issue_number": "48"},
    ],
    2: [
        {"id": 201, "issue_number": "1"},
        {"id": 202, "issue_number": "4"},
        {"id": 203, "issue_number": "10"},
    ],
    3: [
        {"id": 301, "issue_number": "1"},
    ],
}

FULL_DEPS = {
    1: {
        "blocking": [
            {"source_issue_id": 101, "target_issue_id": 102},
            {"source_issue_id": 102, "target_issue_id": 103},
            {"source_issue_id": 103, "target_issue_id": 201},
        ],
        "blocked_by": [],
    },
    2: {
        "blocking": [
            {"source_issue_id": 201, "target_issue_id": 202},
            {"source_issue_id": 202, "target_issue_id": 301},
            {"source_issue_id": 301, "target_issue_id": 203},
        ],
        "blocked_by": [
            {"source_issue_id": 103, "target_issue_id": 201},
            {"source_issue_id": 202, "target_issue_id": 301},
        ],
    },
    3: {
        "blocking": [],
        "blocked_by": [
            {"source_issue_id": 202, "target_issue_id": 301},
        ],
    },
}

STORMWATCH_CHAIN = [
    ("Stormwatch Vol. 1", "37"),
    ("Stormwatch Vol. 1", "43"),
    ("Stormwatch Vol. 1", "48"),
    ("Stormwatch Vol. 2", "1"),
    ("Stormwatch Vol. 2", "4"),
    ("WildC.A.T.s/Aliens", "1"),
    ("Stormwatch Vol. 2", "10"),
]


class TestVerifyReadingOrderAllPresent:
    """Test case where all expected dependencies are present."""

    @patch("comic_pile_api.requests.get")
    def test_all_dependencies_present(self, mock_get: MagicMock) -> None:
        """Verify all chain edges are reported as present when they exist."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)

        result = verify_reading_order([STORMWATCH_CHAIN], "fake-token")

        assert len(result["present"]) == 6
        assert len(result["missing"]) == 0
        assert len(result["unexpected"]) == 0
        assert len(result["not_found"]) == 0

    @patch("comic_pile_api.requests.get")
    def test_present_edges_have_correct_labels(self, mock_get: MagicMock) -> None:
        """Verify that present edges contain correct title/issue labels."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)

        result = verify_reading_order([STORMWATCH_CHAIN], "fake-token")

        first = result["present"][0]
        assert first == DepEdge("Stormwatch Vol. 1", "37", "Stormwatch Vol. 1", "43")

    @patch("comic_pile_api.requests.get")
    def test_empty_chains_returns_empty(self, mock_get: MagicMock) -> None:
        """Verify that empty chains produce empty result lists."""
        mock_get.side_effect = _make_get_handler({}, {}, {})

        result = verify_reading_order([], "fake-token")

        assert result["present"] == []
        assert result["missing"] == []
        assert result["unexpected"] == []
        assert result["not_found"] == []


class TestVerifyReadingOrderOneMissing:
    """Test case where one expected dependency is missing."""

    @patch("comic_pile_api.requests.get")
    def test_one_missing_dependency(self, mock_get: MagicMock) -> None:
        """Verify a single missing edge is correctly reported."""
        partial_deps = {
            1: {
                "blocking": [
                    {"source_issue_id": 101, "target_issue_id": 102},
                    {"source_issue_id": 103, "target_issue_id": 201},
                ],
                "blocked_by": [],
            },
            2: {
                "blocking": [
                    {"source_issue_id": 201, "target_issue_id": 202},
                    {"source_issue_id": 202, "target_issue_id": 301},
                    {"source_issue_id": 301, "target_issue_id": 203},
                ],
                "blocked_by": [
                    {"source_issue_id": 103, "target_issue_id": 201},
                    {"source_issue_id": 202, "target_issue_id": 301},
                ],
            },
            3: {
                "blocking": [],
                "blocked_by": [
                    {"source_issue_id": 202, "target_issue_id": 301},
                ],
            },
        }
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, partial_deps)

        result = verify_reading_order([STORMWATCH_CHAIN], "fake-token")

        assert len(result["present"]) == 5
        assert len(result["missing"]) == 1
        assert result["missing"][0] == DepEdge("Stormwatch Vol. 1", "43", "Stormwatch Vol. 1", "48")

    @patch("comic_pile_api.requests.get")
    def test_unexpected_dependency_detected(self, mock_get: MagicMock) -> None:
        """Verify an extra dependency not in the spec is reported as unexpected."""
        extra_deps = {
            1: {
                "blocking": [
                    {"source_issue_id": 101, "target_issue_id": 102},
                    {"source_issue_id": 102, "target_issue_id": 103},
                    {"source_issue_id": 103, "target_issue_id": 201},
                    {"source_issue_id": 101, "target_issue_id": 103},
                ],
                "blocked_by": [],
            },
            2: {
                "blocking": [
                    {"source_issue_id": 201, "target_issue_id": 202},
                    {"source_issue_id": 202, "target_issue_id": 301},
                    {"source_issue_id": 301, "target_issue_id": 203},
                ],
                "blocked_by": [
                    {"source_issue_id": 103, "target_issue_id": 201},
                    {"source_issue_id": 202, "target_issue_id": 301},
                ],
            },
            3: {
                "blocking": [],
                "blocked_by": [
                    {"source_issue_id": 202, "target_issue_id": 301},
                ],
            },
        }
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, extra_deps)

        result = verify_reading_order([STORMWATCH_CHAIN], "fake-token")

        assert len(result["present"]) == 6
        assert len(result["unexpected"]) == 1
        assert result["unexpected"][0] == DepEdge(
            "Stormwatch Vol. 1", "37", "Stormwatch Vol. 1", "48"
        )

    @patch("comic_pile_api.requests.get")
    def test_multiple_missing_and_unexpected(self, mock_get: MagicMock) -> None:
        """Verify sparse deps produce correct missing and unexpected counts."""
        sparse_deps = {
            1: {
                "blocking": [
                    {"source_issue_id": 101, "target_issue_id": 103},
                ],
                "blocked_by": [],
            },
            2: {
                "blocking": [
                    {"source_issue_id": 201, "target_issue_id": 203},
                ],
                "blocked_by": [],
            },
            3: {
                "blocking": [],
                "blocked_by": [],
            },
        }
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, sparse_deps)

        result = verify_reading_order([STORMWATCH_CHAIN], "fake-token")

        assert len(result["present"]) == 0
        assert len(result["missing"]) == 6
        assert len(result["unexpected"]) == 2


class TestVerifyReadingOrderThreadNotFound:
    """Test case where a thread title doesn't exist."""

    @patch("comic_pile_api.requests.get")
    def test_missing_thread_raises_value_error(self, mock_get: MagicMock) -> None:
        """Verify ValueError raised when a thread title is not found."""
        partial_threads = {
            "Stormwatch Vol. 1": {"id": 1, "title": "Stormwatch Vol. 1"},
            "Stormwatch Vol. 2": {"id": 2, "title": "Stormwatch Vol. 2"},
            "WildC.A.T.s/Aliens": {"id": 3, "title": "WildC.A.T.s/Aliens"},
        }
        mock_get.side_effect = _make_get_handler(partial_threads, ISSUES, FULL_DEPS)

        chain_with_unknown = [
            [("Stormwatch Vol. 1", "37"), ("Stormwatch Vol. 2", "1"), ("Nonexistent Thread", "1")],
        ]

        with pytest.raises(ValueError, match="Thread not found: Nonexistent Thread"):
            verify_reading_order(chain_with_unknown, "fake-token")

    @patch("comic_pile_api.requests.get")
    def test_missing_thread_in_second_chain(self, mock_get: MagicMock) -> None:
        """Verify ValueError raised when second chain references missing thread."""
        mini_threads = {
            "Planetary": {"id": 10, "title": "Planetary"},
        }
        mini_issues = {
            10: [
                {"id": 1001, "issue_number": "1"},
                {"id": 1002, "issue_number": "6"},
            ],
        }
        mock_get.side_effect = _make_get_handler(mini_threads, mini_issues, {})

        chain_with_missing = [
            [("Planetary", "1"), ("Planetary", "6")],
            [("Planetary", "6"), ("The Authority", "1")],
        ]

        with pytest.raises(ValueError, match="Thread not found: The Authority"):
            verify_reading_order(chain_with_missing, "fake-token")


class TestVerifyReadingOrderIssueNotFound:
    """Test case where a spec edge references an issue number not in the DB."""

    @patch("comic_pile_api.requests.get")
    def test_nonexistent_source_issue_reported_as_not_found(self, mock_get: MagicMock) -> None:
        """Verify edge with nonexistent source issue appears in not_found."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)

        chain = [
            ("Stormwatch Vol. 1", "99"),
            ("Stormwatch Vol. 2", "1"),
        ]

        result = verify_reading_order([chain], "fake-token")

        assert len(result["not_found"]) == 1
        assert result["not_found"][0] == DepEdge(
            "Stormwatch Vol. 1", "99", "Stormwatch Vol. 2", "1"
        )
        assert len(result["present"]) == 0
        assert len(result["missing"]) == 0

    @patch("comic_pile_api.requests.get")
    def test_nonexistent_target_issue_reported_as_not_found(self, mock_get: MagicMock) -> None:
        """Verify edge with nonexistent target issue appears in not_found."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)

        chain = [
            ("Stormwatch Vol. 1", "37"),
            ("Stormwatch Vol. 1", "99"),
        ]

        result = verify_reading_order([chain], "fake-token")

        assert len(result["not_found"]) == 1
        assert result["not_found"][0] == DepEdge(
            "Stormwatch Vol. 1", "37", "Stormwatch Vol. 1", "99"
        )

    @patch("comic_pile_api.requests.get")
    def test_both_issues_nonexistent(self, mock_get: MagicMock) -> None:
        """Verify edge with both nonexistent issues appears in not_found."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)

        chain = [
            ("Stormwatch Vol. 1", "77"),
            ("Stormwatch Vol. 2", "99"),
        ]

        result = verify_reading_order([chain], "fake-token")

        assert len(result["not_found"]) == 1
        assert result["not_found"][0] == DepEdge(
            "Stormwatch Vol. 1", "77", "Stormwatch Vol. 2", "99"
        )

    @patch("comic_pile_api.requests.get")
    def test_mixed_found_and_not_found_in_chain(self, mock_get: MagicMock) -> None:
        """Verify chain with some valid and some nonexistent issues splits correctly."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)

        chain = [
            ("Stormwatch Vol. 1", "37"),
            ("Stormwatch Vol. 1", "43"),
            ("Stormwatch Vol. 1", "99"),
            ("Stormwatch Vol. 2", "1"),
        ]

        result = verify_reading_order([chain], "fake-token")

        assert len(result["present"]) == 1
        assert result["present"][0] == DepEdge("Stormwatch Vol. 1", "37", "Stormwatch Vol. 1", "43")
        assert len(result["not_found"]) == 2
        assert DepEdge("Stormwatch Vol. 1", "43", "Stormwatch Vol. 1", "99") in result["not_found"]
        assert DepEdge("Stormwatch Vol. 1", "99", "Stormwatch Vol. 2", "1") in result["not_found"]


MINI_CHAINS: list[list[tuple[str, str]]] = [
    [
        ("Stormwatch Vol. 1", "37"),
        ("Stormwatch Vol. 1", "43"),
        ("Stormwatch Vol. 1", "48"),
    ],
]


class TestArgParsing:
    """Tests for command-line argument parsing."""

    def test_no_flags_defaults(self) -> None:
        """Verify no flags means neither verify nor fix."""
        args = _parse_args([])
        assert args.verify is False
        assert args.fix is False

    def test_verify_flag(self) -> None:
        """Verify --verify flag sets verify=True."""
        args = _parse_args(["--verify"])
        assert args.verify is True
        assert args.fix is False

    def test_fix_flag(self) -> None:
        """Verify --fix flag sets fix=True."""
        args = _parse_args(["--fix"])
        assert args.verify is False
        assert args.fix is True

    def test_verify_and_fix_mutually_exclusive(self) -> None:
        """Verify --verify and --fix cannot be used together."""
        with pytest.raises(SystemExit):
            _parse_args(["--verify", "--fix"])


class TestRunVerify:
    """Tests for the --verify flag behaviour."""

    @patch("comic_pile_api.requests.post")
    @patch("comic_pile_api.requests.get")
    def test_verify_returns_zero_when_all_present(
        self, mock_get: MagicMock, mock_post: MagicMock
    ) -> None:
        """Verify --verify returns 0 when all deps are present."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)
        mock_post.return_value = MagicMock()

        exit_code = run_verify("fake-token", MINI_CHAINS)

        assert exit_code == 0
        mock_post.assert_not_called()

    @patch("comic_pile_api.requests.post")
    @patch("comic_pile_api.requests.get")
    def test_verify_returns_one_when_missing(
        self, mock_get: MagicMock, mock_post: MagicMock
    ) -> None:
        """Verify --verify returns 1 when deps are missing."""
        partial_deps = {
            1: {
                "blocking": [
                    {"source_issue_id": 101, "target_issue_id": 102},
                ],
                "blocked_by": [],
            },
            2: {"blocking": [], "blocked_by": []},
            3: {"blocking": [], "blocked_by": []},
        }
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, partial_deps)
        mock_post.return_value = MagicMock()

        exit_code = run_verify("fake-token", MINI_CHAINS)

        assert exit_code == 1
        mock_post.assert_not_called()

    @patch("comic_pile_api.requests.post")
    @patch("comic_pile_api.requests.get")
    def test_verify_does_not_create_deps(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        """Verify --verify never calls create_dependency (no POST to dependencies endpoint)."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)
        mock_post.return_value = MagicMock()

        run_verify("fake-token", MINI_CHAINS)

        mock_post.assert_not_called()


class TestRunFix:
    """Tests for the --fix flag behaviour."""

    @patch("comic_pile_api.requests.post")
    @patch("comic_pile_api.requests.get")
    def test_fix_creates_only_missing_deps(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        """Verify --fix creates only the missing dependencies, not present ones."""
        partial_deps = {
            1: {
                "blocking": [
                    {"source_issue_id": 101, "target_issue_id": 102},
                ],
                "blocked_by": [],
            },
            2: {"blocking": [], "blocked_by": []},
            3: {"blocking": [], "blocked_by": []},
        }
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, partial_deps)
        dep_response = MagicMock()
        dep_response.status_code = 201
        mock_post.return_value = dep_response

        exit_code = run_fix("fake-token", MINI_CHAINS)

        assert exit_code == 0
        dep_calls = [call for call in mock_post.call_args_list if "/dependencies/" in str(call)]
        assert len(dep_calls) == 1

    @patch("comic_pile_api.requests.post")
    @patch("comic_pile_api.requests.get")
    def test_fix_noop_when_all_present(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        """Verify --fix does nothing when all deps are already present."""
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, FULL_DEPS)
        dep_response = MagicMock()
        dep_response.status_code = 201
        mock_post.return_value = dep_response

        exit_code = run_fix("fake-token", MINI_CHAINS)

        assert exit_code == 0
        dep_calls = [call for call in mock_post.call_args_list if "/dependencies/" in str(call)]
        assert len(dep_calls) == 0

    @patch("comic_pile_api.requests.post")
    @patch("comic_pile_api.requests.get")
    def test_fix_does_not_recreate_present_deps(
        self, mock_get: MagicMock, mock_post: MagicMock
    ) -> None:
        """Verify --fix only creates the missing edges, not the already-present one."""
        partial_deps = {
            1: {
                "blocking": [
                    {"source_issue_id": 101, "target_issue_id": 103},
                ],
                "blocked_by": [],
            },
            2: {"blocking": [], "blocked_by": []},
            3: {"blocking": [], "blocked_by": []},
        }
        mock_get.side_effect = _make_get_handler(THREADS, ISSUES, partial_deps)
        dep_response = MagicMock()
        dep_response.status_code = 201
        mock_post.return_value = dep_response

        exit_code = run_fix("fake-token", MINI_CHAINS)

        assert exit_code == 0
        dep_calls = [call for call in mock_post.call_args_list if "/dependencies/" in str(call)]
        assert len(dep_calls) == 2
