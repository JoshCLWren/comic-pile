"""Coverage for the trusted review-findings fetch/format helper.

Factory workers inject this file into every PR mission so Greptile findings
are treated as high-priority, must-address review feedback.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/scripts/factory-review-findings.sh"
SCRIPTS = ROOT / ".github/scripts"
HEAD = "a" * 40
OLD_HEAD = "b" * 40


def run_bash(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f"set -Eeuo pipefail; source {HELPER!s}; {script}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, **(env or {})},
    )


def thread(
    login: str,
    body: str,
    *,
    resolved: bool = False,
    outdated: bool = False,
    path: str = "app/x.py",
    line: int | None = 7,
    replies: list[tuple[str, str]] | None = None,
) -> dict:
    comments: list[dict[str, Any]] = [
        {"author": {"login": login}, "body": body, "url": f"https://example.test/{login}"}
    ]
    comments += [
        {"author": {"login": who}, "body": text, "url": None} for who, text in replies or []
    ]
    return {
        "id": f"PRRT_{login}_{line}",
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
        "line": line,
        "originalLine": 3,
        "comments": {"nodes": comments},
    }


GREPTILE_BODY = """Intro text
<!-- greptile_comment -->
<!-- greptile_summary -->
Confidence Score: 3/5
1. **Race in claim loop**
<!-- /greptile_comment -->
Trailing author text
"""


def write_inputs(
    tmp_path: Path,
    threads: list[dict],
    *,
    reviews: list[dict] | None = None,
    body: str = GREPTILE_BODY,
    checks: list[dict] | None = None,
) -> list[Path]:
    paths = [
        tmp_path / name for name in ("threads.json", "reviews.json", "body.txt", "checks.json")
    ]
    paths[0].write_text(
        json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": threads}}}}})
    )
    paths[1].write_text(json.dumps(reviews or []))
    paths[2].write_text(body)
    paths[3].write_text(json.dumps({"check_runs": checks or []}))
    return paths


def format_findings(tmp_path: Path, **kwargs) -> str:
    threads = kwargs.pop("threads", [])
    files = write_inputs(tmp_path, threads, **kwargs)
    result = run_bash(f"factory_format_review_findings {' '.join(map(str, files))} 42 {HEAD}")
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_greptile_findings_are_listed_first_and_high_priority(tmp_path: Path) -> None:
    out = format_findings(
        tmp_path,
        threads=[
            thread("some-human", "Human nit about naming", line=1),
            thread("greptile-apps", "**Unbounded retry** in loop\nPrompt To Fix With AI", line=9),
            thread("pr-agent", "bot remark", line=2),
        ],
    )
    high = out.index("## HIGH PRIORITY: Greptile findings (must address)")
    greptile = out.index("HIGH PRIORITY G1. app/x.py:9")
    other = out.index("## Other unresolved review threads")
    human = out.index("R1. app/x.py:1")
    assert high < greptile < other < human
    assert "Unbounded retry" in out[greptile:other]
    assert "Human nit" not in out[greptile:other]
    assert "R2. app/x.py:2" in out
    assert "FIXED IN CODE" in out and "EVIDENCE-BACKED REBUTTAL" in out
    assert "never resolve a thread silently" in out


def test_resolved_threads_are_excluded_and_outdated_are_flagged(tmp_path: Path) -> None:
    out = format_findings(
        tmp_path,
        threads=[
            thread("greptile-apps", "already fixed", resolved=True, line=4),
            thread("greptile-apps[bot]", "old anchor", outdated=True, line=None),
        ],
    )
    assert "already fixed" not in out
    assert "HIGH PRIORITY G1. app/x.py:3 (original line) [OUTDATED" in out
    assert "HIGH PRIORITY G2" not in out


def test_replies_are_included_so_rebuttals_are_visible(tmp_path: Path) -> None:
    out = format_findings(
        tmp_path,
        threads=[
            thread(
                "greptile-apps", "finding", replies=[("JoshCLWren", "Rebuttal: see tests/x.py:10")]
            ),
        ],
    )
    assert "Replies so far:\n- JoshCLWren: Rebuttal: see tests/x.py:10" in out


def test_greptile_review_body_and_pr_summary_are_included(tmp_path: Path) -> None:
    out = format_findings(
        tmp_path,
        reviews=[
            {
                "user": {"login": "greptile-apps[bot]"},
                "body": "old review",
                "commit_id": OLD_HEAD,
                "submitted_at": "2026-10-18T01:00:00Z",
            },
            {
                "user": {"login": "greptile-apps[bot]"},
                "body": "latest review",
                "commit_id": HEAD,
                "submitted_at": "2026-10-18T02:00:00Z",
            },
            {
                "user": {"login": "greptile-apps[bot]"},
                "body": "",
                "commit_id": HEAD,
                "submitted_at": "2026-10-18T03:00:00Z",
            },
            {
                "user": {"login": "someone"},
                "body": "not greptile",
                "commit_id": HEAD,
                "submitted_at": "2026-10-18T04:00:00Z",
            },
        ],
    )
    review = out[
        out.index("### Greptile top-level review body") : out.index("### Greptile PR-body summary")
    ]
    assert "latest review" in review and "(current head)" in review
    assert "old review" not in review and "not greptile" not in review
    summary = out[out.index("### Greptile PR-body summary") : out.index("## Other unresolved")]
    assert "Confidence Score: 3/5" in summary and "Race in claim loop" in summary
    assert "Intro text" not in summary and "Trailing author text" not in summary
    assert "greptile_comment" not in summary


def test_pr_agent_check_output_is_lower_priority_advisory(tmp_path: Path) -> None:
    out = format_findings(
        tmp_path,
        checks=[
            {
                "name": "PR Agent - Review",
                "conclusion": "neutral",
                "output": {
                    "title": "PR-Agent advisory review",
                    "summary": "s",
                    "text": "Possible bug in parser",
                },
            },
            {
                "name": "Backend tests",
                "conclusion": "success",
                "output": {"title": "ignored", "summary": None, "text": None},
            },
        ],
    )
    advisory = out.index("## Lower priority: PR-Agent advisory review")
    assert out.index("## HIGH PRIORITY") < advisory
    assert "Possible bug in parser" in out[advisory:]
    assert "Backend tests" not in out


def test_empty_inputs_say_none(tmp_path: Path) -> None:
    out = format_findings(tmp_path, body="no greptile here")
    assert "No unresolved Greptile review threads." in out
    assert out.count("None.") == 4


def test_long_bodies_are_clipped(tmp_path: Path) -> None:
    files = write_inputs(tmp_path, [thread("greptile-apps", "x" * 500)])
    result = run_bash(
        f"factory_format_review_findings {' '.join(map(str, files))} 42 {HEAD}",
        env={"FACTORY_REVIEW_FINDINGS_BODY_LIMIT": "50"},
    )
    assert result.returncode == 0, result.stderr
    assert "x" * 51 not in result.stdout
    assert "truncated by factory wrapper" in result.stdout


def fake_gh(tmp_path: Path, *, fail: bool = False) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    graphql = json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                thread("some-human", "human comment", line=1),
                                thread("greptile-apps", "greptile finding", line=5),
                            ]
                        }
                    }
                }
            }
        }
    )
    script = bin_dir / "gh"
    if fail:
        script.write_text("#!/usr/bin/env bash\necho boom >&2\nexit 1\n")
    else:
        script.write_text(f"""#!/usr/bin/env bash
echo "$*" >> {tmp_path}/gh-calls.log
case "$*" in
  *graphql*) cat <<'JSON'
{graphql}
JSON
  ;;
  *pulls/42/reviews*) echo '[]' ;;
  "pr view 42"*) printf '%s' 'x <!-- greptile_comment -->S<!-- /greptile_comment -->' ;;
  *check-runs*) echo '{{"check_runs":[{{"name":"PR-Agent advisory review","conclusion":"neutral","output":{{"title":"t","summary":"advice","text":null}}}}]}}' ;;
  *) exit 1 ;;
esac
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "JoshCLWren/comic-pile",
    }


def test_mission_fetches_writes_file_and_injects_greptile_first(tmp_path: Path) -> None:
    out_file = tmp_path / "findings.md"
    result = run_bash(
        f"factory_review_findings_mission 42 {HEAD} {out_file}", env=fake_gh(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    text = result.stdout
    assert out_file.exists()
    assert out_file.read_text().strip() in text
    assert "HIGH PRIORITY, must-address" in text
    assert text.index("greptile finding") < text.index("human comment")
    assert "advice" in text
    calls = (tmp_path / "gh-calls.log").read_text()
    assert f"commits/{HEAD}/check-runs" in calls
    assert "isOutdated" in calls and "author{login}" in calls


def test_fetch_failure_never_fails_the_wrapper(tmp_path: Path) -> None:
    out_file = tmp_path / "findings.md"
    result = run_bash(
        f"factory_review_findings_mission 42 {HEAD} {out_file}", env=fake_gh(tmp_path, fail=True)
    )
    assert result.returncode == 0, result.stderr
    assert (
        "WARNING: the wrapper could not fetch or format: review threads,review submissions,PR body,check runs"
        in result.stdout
    )


def test_every_worker_pr_mission_injects_review_findings() -> None:
    for name in (
        "omniroute-factory-worker.sh",
        "free-model-factory-worker-primitives.sh",
        "free-model-factory-worker.sh",
        "nvidia-factory-worker.sh",
    ):
        source = (SCRIPTS / name).read_text()
        missions = source.count('mission="Resume this PR.')
        assert missions >= 1, name
        assert source.count('findings="$(factory_review_findings_mission "$number"') == missions, (
            name
        )
        assert 'mission+=" ${findings}"' in source, name
        assert "Greptile (greptile-apps[bot]) review findings are HIGH PRIORITY" in source, name
    for name in (
        "omniroute-factory-worker.sh",
        "free-model-factory-worker-primitives.sh",
        "nvidia-factory-worker.sh",
    ):
        source = (SCRIPTS / name).read_text()
        assert "source .github/scripts/factory-review-findings.sh" in source, name
        # The helper is loaded at startup, before any PR branch checkout.
        assert source.index("factory-review-findings.sh") < source.index("checkout_target() {"), (
            name
        )


def test_semantic_recovery_prompt_requires_greptile_findings_addressed() -> None:
    source = (SCRIPTS / "factory-semantic-verdict.sh").read_text()
    assert "EVERY Greptile finding was either fixed in code" in source
    assert "must be FACTORY_GATE_BLOCKED and never FACTORY_GATE_READY" in source
