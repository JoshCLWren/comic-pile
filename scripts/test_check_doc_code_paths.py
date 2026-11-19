"""Deterministic tests for scripts/check_doc_code_paths.py (run with ``python -m unittest``)."""

from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

checker = importlib.import_module("check_doc_code_paths")


def _run(files: dict[str, str]) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, body in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        docs = sorted(root.rglob("*.md"))
        return checker.find_stale_paths(root, docs)


class DocCodePathTests(unittest.TestCase):
    """Behavior of the doc code-path checker on synthetic repositories."""

    def test_existing_paths_pass(self) -> None:
        """Existing paths pass."""
        errors = _run(
            {
                "README.md": "See `native/lib.rs`, `native/lib.rs:12`, and `src/util.py`.\n",
                "native/lib.rs": "",
                "src/util.py": "",
            }
        )
        self.assertEqual(errors, [])

    def test_missing_path_fails_with_location(self) -> None:
        """Missing path fails with location."""
        errors = _run({"README.md": "ok\nSee `app/api/gone.py` here.\n"})
        self.assertEqual(errors, ["README.md:2: stale code path: app/api/gone.py"])

    def test_missing_bare_code_filename_fails(self) -> None:
        """Missing bare code filename fails."""
        errors = _run({"docs/a.md": "Edit `renamed_module.py`.\n"})
        self.assertEqual(len(errors), 1)

    def test_bare_filename_matching_any_tracked_basename_passes(self) -> None:
        """Bare filename matching any tracked basename passes."""
        errors = _run({"docs/a.md": "Edit `lib.rs`.\n", "native/x/lib.rs": ""})
        self.assertEqual(errors, [])

    def test_sibling_relative_path_passes(self) -> None:
        """Sibling relative path passes."""
        errors = _run(
            {"docs/a.md": "See `b.md`, `sub/c.md`.\n", "docs/b.md": "", "docs/sub/c.md": ""}
        )
        self.assertEqual(errors, [])

    def test_fenced_blocks_globs_placeholders_and_generated_output_are_ignored(self) -> None:
        """Fenced blocks globs placeholders and generated output are ignored."""
        body = (
            "```\n`app/gone.py`\n```\n"
            "Glob `app/*.py`, template `app/<name>.py`, brace `app/{a,b}.py`, "
            "dated `out/db_export_YYYYMMDD.json`, build `static/react/index.html`, "
            "bare data `results.json`, url `https://x.test/a/b.py`.\n"
        )
        self.assertEqual(_run({"README.md": body}), [])

    def test_ignore_line_marker_and_historical_file_marker(self) -> None:
        """Ignore line marker and historical file marker."""
        marked = "Old `app/gone.py`. <!-- docs-path-check: ignore -->\nNew `app/gone2.py`.\n"
        self.assertEqual(len(_run({"README.md": marked})), 1)
        historical = "<!-- docs-path-check: historical -->\nOld `app/gone.py`.\n"
        self.assertEqual(_run({"README.md": historical}), [])

    def test_historical_prefixes_are_skipped(self) -> None:
        """Historical prefixes are skipped."""
        self.assertEqual(_run({"docs/issue-plans/1.md": "Old `app/gone.py`.\n"}), [])

    def test_current_repository_has_no_stale_code_paths(self) -> None:
        """Current repository has no stale code paths."""
        root = Path(__file__).resolve().parents[1]
        errors = checker.find_stale_paths(root, checker.iter_markdown_files(root))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
