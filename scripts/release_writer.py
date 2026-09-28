#!/usr/bin/env python3
"""Validate release-writer payloads and keep credentials outside model prompts."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import NoReturn

_ALLOWED_VISIBILITY = {"public", "internal"}
_ALLOWED_STATUS = {"draft", "published", "retracted"}
_REQUIRED = {
    "source_repository",
    "source_pr_number",
    "source_merge_sha",
    "merged_at",
    "released_at",
    "category",
    "title",
    "summary",
}
_GITHUB_API_BASE = "https://api.github.com"
_ISSUE_REFERENCE_PATTERN = re.compile(r"(?<!\w)#(\d{1,7})\b")
_ORDINAL_INDICATORS = {"step", "build", "section", "phase", "version", "stage", "v"}
_VERSION_STEP_PATTERN = re.compile(r"v?\d+(?:\.\d+)*")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?:\/\/[^)]+)\)")
_BACKTICK_PATTERN = re.compile(r"`([^`]+)`")
_MIN_PUBLIC_CONTENT = {"category": 2, "title": 4, "summary": 12}
_READER_FACING_FIELDS = ("category", "title", "summary")

_TICKET_REFERENCE_PATTERN = re.compile(r"(?<![\w&])#\d{1,7}\b")
_SCHEMA_IDENTIFIER_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_PHASE_TERMINOLOGY_PATTERN = re.compile(
    r"\bphases?\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_UNFINISHED_WORK_PATTERN = re.compile(
    r"\b(?:incomplete|unfinished|todo|wip|not yet implemented)\b",
    re.IGNORECASE,
)

_KNOWN_TYPOS: dict[str, str] = {
    "appearnence": "appearance",
    "appearence": "appearance",
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "seperated": "separated",
    "occured": "occurred",
    "untill": "until",
    "definately": "definitely",
    "accross": "across",
    "existance": "existence",
    "persistant": "persistent",
    "successfull": "successful",
    "compatability": "compatibility",
}

# Decisive scope fences that mean "the reader-visible portion is not in this
# change". Detected deterministically so a weaker model cannot simply overlook
# the fence that contradicts a public claim. Phrasings are grounded in the real
# issue text behind the #2910 and #2916 false positives.
_SCOPE_FENCE_SOURCES: tuple[tuple[str, str], ...] = (
    (r"\bno\s+frontend\s+(?:caller|consumer|ui|change)", "no frontend callers"),
    (r"\bno\s+(?:\w+[\s/-]+){0,3}ui\b", "no shipped ui"),
    (
        r"\bui\b[^\n.]{0,60}\b(?:out\s+of\s+scope|not\s+included|not\s+shipped|unshipped"
        r"|deferred|excluded|owned\s+by)\b",
        "ui not shipped",
    ),
    (r"\bdo\s+not\s+add\b[^\n.]{0,40}\bui\b", "ui not shipped"),
    (r"\b(?:defer|deferred|defers)\w*\b[^\n.]{0,40}\bui\b", "ui deferred"),
    (r"\bscope\s+fence\b", "scope fence"),
    (r"\bout\s+of\s+scope\b", "out of scope"),
    (r"\b(?:not|non)[\s-]*user[\s-]*visible\b", "not user visible"),
    (r"\bnot\s+reader[\s-]*reachable\b", "not reader reachable"),
    (r"\binternal[\s-]*only\b", "internal only"),
    (r"\b(?:internal|implementation|behavioural|behavioral)\s+refactor\b", "internal refactor"),
    (r"\bbehaviou?r\s+(?:is\s+)?(?:preserved|unchanged)\b", "behavior preserved"),
    (
        r"\b(?:backend|api|server)[\s-]*(?:only\s+)?(?:prerequisite|enablement)\b",
        "backend prerequisite",
    ),
    (
        r"\bno\s+(?:current\s+|supported\s+)?(?:product|user|reader)\s+(?:caller|path|surface)\b",
        "no product caller",
    ),
    (r"\bfollow[\s-]*up\s+(?:ui|work)\b", "follow-up user surface"),
    (r"\b(?:staged|partial|phased)\s+rollout\b", "staged rollout"),
)
_SCOPE_FENCE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), label)
    for pattern, label in _SCOPE_FENCE_SOURCES
)

# Reader-facing capability claims. A public note may only promise a new reader
# capability when the merged diff actually changes a reader-reachable surface or
# the model documents the contradiction explicitly.
_CAPABILITY_CLAIM_PATTERN = re.compile(
    r"\b(?:you can now|can now|now\s+(?:supports|includes|lets\s+you|handles)"
    r"|(?:is|are)\s+now\s+available)\b",
    re.IGNORECASE,
)
# Tracked reader-facing surfaces. `static/` covers the shipped shell, its styles,
# and the built React bundle; `templates/` does not exist in this repository and
# `static/react/` is gitignored build output rather than a committable diff path.
_READER_SURFACE_PREFIXES = ("frontend/src/", "frontend/public/", "static/")

_PUBLIC_EVIDENCE_TEXT_LIMITS: dict[str, int] = {
    "classification_reason": 1000,
    "user_visible_evidence": 2000,
    "reader_reachable_path": 500,
}
_MIN_USER_VISIBLE_EVIDENCE = 20
_RELATIONSHIP_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpart\s+of\s*$", re.IGNORECASE), "parent"),
    (re.compile(r"\bchild\s+of\s*$", re.IGNORECASE), "parent"),
    (re.compile(r"\bsplit\s+from\s*$", re.IGNORECASE), "parent"),
    (re.compile(r"\bdepends\s+on\s*$", re.IGNORECASE), "dependency"),
    (re.compile(r"\bblocked\s+by\s*$", re.IGNORECASE), "dependency"),
    (re.compile(r"\brequires\s*$", re.IGNORECASE), "dependency"),
    (re.compile(r"\bafter\s*$", re.IGNORECASE), "dependency"),
    (re.compile(r"\bfollow[\s-]?up\b[^\n.]{0,30}$", re.IGNORECASE), "follow-up"),
    (re.compile(r"\bduplicate\s+of\s*$", re.IGNORECASE), "related"),
    (re.compile(r"\brelated\s+to\s*$", re.IGNORECASE), "related"),
    (re.compile(r"\bsee\s+also\s*$", re.IGNORECASE), "related"),
)
_RELATIONSHIP_WINDOW = 48
_MAX_ISSUE_REFERENCES = 25
_MAX_ISSUE_BODY = 4000


def _visible_release_text(value: object) -> str:
    """Return release copy as readers see it after stripping Markdown formatting.

    Args:
        value: Raw release copy that may contain Markdown links or backticks.

    Returns:
        The visible text with link syntax resolved and backticks unwrapped.
    """
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", str(value))
    return _BACKTICK_PATTERN.sub(r"\1", text)


def _reader_facing_error(field_name: str, value: object) -> str | None:
    """Describe the first internal engineering artifact in reader-facing copy.

    Args:
        field_name: Name of the release field being inspected.
        value: Raw release copy that may hide internal artifacts behind Markdown.

    Returns:
        A human-readable failure message, or None when the copy reads as
        ordinary reader-facing product language.
    """
    text = _visible_release_text(value)
    for pattern, kind in (
        (_TICKET_REFERENCE_PATTERN, "internal ticket reference"),
        (_SCHEMA_IDENTIFIER_PATTERN, "database/schema identifier"),
        (_PHASE_TERMINOLOGY_PATTERN, "implementation phase terminology"),
        (_UNFINISHED_WORK_PATTERN, "unfinished-work commentary"),
    ):
        match = pattern.search(text)
        if match:
            fragment = match.group(0).strip()
            return (
                f"{field_name} must use reader-facing product language: "
                f"{kind} '{fragment}'"
            )
    lowered = text.lower()
    for wrong, right in _KNOWN_TYPOS.items():
        if re.search(rf"\b{wrong}\b", lowered):
            return (
                f"{field_name} must be spell-checked before publication: "
                f"'{wrong}' (did you mean '{right}'?)"
            )
    return None


def _display_length(value: object) -> int:
    """Return the visible length of release copy after stripping Markdown formatting.

    Args:
        value: Raw release copy that may contain Markdown links or backticks.

    Returns:
        The number of visible characters in the stripped text.
    """
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", str(value))
    text = _BACKTICK_PATTERN.sub(r"\1", text)
    return len(text.strip())


def _fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _api_base() -> str:
    value = os.getenv("RELEASE_API_URL", "").strip().rstrip("/")
    if not value:
        _fail("RELEASE_API_URL is required")
    return value


def _token() -> str:
    value = os.getenv("RELEASE_WRITER_TOKEN", "").strip()
    if not value:
        _fail("RELEASE_WRITER_TOKEN is required")
    return value


def _request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Release-Writer-Token": _token(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        _fail(f"release API returned HTTP {exc.code}: {detail[:1000]}")
    except urllib.error.URLError as exc:
        _fail(f"release API request failed: {exc.reason}")


def _github_request(url: str, *, missing_ok: bool = False) -> object:
    """Perform a read-only GitHub API request.

    Args:
        url: Absolute GitHub API URL.
        missing_ok: When True, a 404 response yields None instead of failing so
            a stale reference cannot abort context collection.

    Returns:
        Decoded JSON payload, or None when a missing resource is tolerated.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ComicPile-release-writer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        detail = exc.read().decode(errors="replace")
        _fail(f"GitHub API returned HTTP {exc.code}: {detail[:1000]}")
    except urllib.error.URLError as exc:
        _fail(f"GitHub API request failed: {exc.reason}")


def _github_read(url: str) -> object | None:
    """Perform a best-effort read used by publish-time grounding checks.

    Grounding only ever blocks on positive evidence, so an unreachable GitHub
    API must not stop a publication that is otherwise valid.

    Args:
        url: Absolute GitHub API URL.

    Returns:
        Decoded JSON payload, or None when the read could not be completed.
    """
    try:
        return _github_request(url, missing_ok=True)
    except SystemExit:
        return None


def _parse_timestamp(value: object, name: str) -> str:
    if not isinstance(value, str):
        _fail(f"{name} must be an ISO-8601 string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{name} must be a valid ISO-8601 timestamp")
    return value


def _validate_release(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"invalid release JSON: {exc}")
    if not isinstance(payload, dict):
        _fail("release payload must be an object")
    missing = sorted(_REQUIRED - payload.keys())
    if missing:
        _fail(f"missing release fields: {', '.join(missing)}")
    if set(payload) - (_REQUIRED | {"body", "visibility", "status", "sort_order", "provenance_json"}):
        _fail("release payload contains unsupported fields")
    repository = payload["source_repository"]
    if not isinstance(repository, str) or not (1 <= len(repository) <= 255):
        _fail("source_repository must be 1..255 characters")
    pr_number = payload["source_pr_number"]
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number < 1:
        _fail("source_pr_number must be a positive integer")
    merge_sha = payload["source_merge_sha"]
    if not isinstance(merge_sha, str) or not (7 <= len(merge_sha) <= 64):
        _fail("source_merge_sha must be 7..64 characters")
    _parse_timestamp(payload["merged_at"], "merged_at")
    _parse_timestamp(payload["released_at"], "released_at")
    for name, maximum in (("category", 100), ("title", 255), ("summary", 1200)):
        value = payload[name]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            _fail(f"{name} must be non-empty and at most {maximum} characters")
    body = payload.get("body")
    if body is not None and (not isinstance(body, str) or len(body) > 6000):
        _fail("body must be null or at most 6000 characters")
    if payload.get("visibility", "public") not in _ALLOWED_VISIBILITY:
        _fail("unsupported visibility")
    if payload.get("status", "published") not in _ALLOWED_STATUS:
        _fail("unsupported status")
    provenance = payload.get("provenance_json", {})
    if not isinstance(provenance, dict):
        _fail("provenance_json must be an object")
    payload.setdefault("visibility", "public")
    payload.setdefault("status", "published")
    payload.setdefault("sort_order", 0)
    payload.setdefault("provenance_json", {})
    if (
        payload["visibility"] == "public"
        and payload["status"] == "published"
    ):
        for name, minimum in _MIN_PUBLIC_CONTENT.items():
            if _display_length(payload[name]) < minimum:
                _fail(
                    f"{name} must contain meaningful release content "
                    f"(at least {minimum} visible characters)"
                )
        for name in _READER_FACING_FIELDS:
            error = _reader_facing_error(name, payload[name])
            if error:
                _fail(error)
        _validate_public_evidence(payload)
    return payload


def _provenance_text(
    provenance: dict[str, object],
    name: str,
    *,
    minimum: int = 1,
) -> str:
    """Return a required provenance text field or fail with a precise message.

    Args:
        provenance: Structured classification provenance from the payload.
        name: Provenance field name being validated.
        minimum: Minimum meaningful character count for the field.

    Returns:
        The stripped provenance text.

    Raises:
        SystemExit: When the field is missing, mistyped, empty, or too short.
    """
    value = provenance.get(name)
    if not isinstance(value, str):
        _fail(
            f"provenance_json.{name} must be a string to justify a public release"
        )
    text = value.strip()
    maximum = _PUBLIC_EVIDENCE_TEXT_LIMITS.get(name, 1000)
    if len(text) < minimum:
        _fail(
            f"provenance_json.{name} must describe the change in at least "
            f"{minimum} characters to justify a public release"
        )
    if len(text) > maximum:
        _fail(f"provenance_json.{name} must be at most {maximum} characters")
    return text


def _provenance_string_list(provenance: dict[str, object], name: str) -> list[str]:
    """Return a provenance string-list field or fail with a precise message.

    Args:
        provenance: Structured classification provenance from the payload.
        name: Provenance field name being validated.

    Returns:
        The non-empty stripped entries of the list.

    Raises:
        SystemExit: When the field is not a list of non-empty strings.
    """
    value = provenance.get(name, [])
    if not isinstance(value, list):
        _fail(f"provenance_json.{name} must be a list of non-empty strings")
    entries: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _fail(f"provenance_json.{name} must be a list of non-empty strings")
        entries.append(item.strip())
    return entries


def _provenance_issue_numbers(provenance: dict[str, object]) -> list[int]:
    """Return the inspected linked issue numbers recorded in provenance.

    Args:
        provenance: Structured classification provenance from the payload.

    Returns:
        Sorted unique positive issue numbers the writer inspected.

    Raises:
        SystemExit: When the field is not a list of positive integers.
    """
    value = provenance.get("inspected_issue_numbers", [])
    if not isinstance(value, list):
        _fail(
            "provenance_json.inspected_issue_numbers must be a list of issue numbers"
        )
    numbers: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            _fail(
                "provenance_json.inspected_issue_numbers must be a list of issue numbers"
            )
        numbers.add(item)
    return sorted(numbers)


def _validate_public_evidence(payload: dict[str, object]) -> None:
    """Require auditable reader-visible evidence before a public publication.

    Args:
        payload: Validated release payload marked public and published.

    Returns:
        None.

    Raises:
        SystemExit: When the classification evidence is absent, mistyped,
            internally inconsistent, or blocked by a declared scope fence.
    """
    provenance = payload["provenance_json"]
    if not isinstance(provenance, dict):
        _fail("provenance_json must be an object")
    if provenance.get("classification") != "public":
        _fail(
            'provenance_json.classification must be "public" for a public release'
        )
    _provenance_text(provenance, "classification_reason")
    _provenance_text(provenance, "user_visible_evidence", minimum=_MIN_USER_VISIBLE_EVIDENCE)
    if provenance.get("reader_reachable") is not True:
        _fail(
            "provenance_json.reader_reachable must be true for a public release; "
            "classify the change as internal when no shipped reader path exists"
        )
    _provenance_issue_numbers(provenance)
    scope_fences = _provenance_string_list(provenance, "scope_fences")
    contradicting = _provenance_string_list(provenance, "contradicting_evidence")
    if scope_fences and not contradicting:
        _fail(
            "linked issue scope fences contradict a public release "
            f"({', '.join(scope_fences)}); classify the change as internal or record "
            "provenance_json.contradicting_evidence explaining the shipped reader path"
        )
    if any(_CAPABILITY_CLAIM_PATTERN.search(str(payload[name])) for name in _READER_FACING_FIELDS):
        _provenance_text(provenance, "reader_reachable_path")


def _capability_claim(payload: dict[str, object]) -> str | None:
    """Return the reader-facing field containing a reader capability claim.

    Args:
        payload: Validated release payload marked public and published.

    Returns:
        The offending field name, or None when the copy claims no new capability.
    """
    for name in _READER_FACING_FIELDS:
        if _CAPABILITY_CLAIM_PATTERN.search(str(payload[name])):
            return name
    return None


def _changed_files(repository: str, number: int) -> list[dict[str, object]]:
    """Return the bounded changed-file summary for one pull request.

    Args:
        repository: Owner/name repository string.
        number: Pull request number.

    Returns:
        Changed-file summaries, or an empty list when the read is unavailable.
    """
    owner, name = _repository_parts(repository)
    query = urllib.parse.urlencode({"per_page": 100})
    result = _github_read(
        f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{number}/files?{query}"
    )
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]


def _linked_scope_fences(repository: str, number: int) -> list[str]:
    """Return scope fences detected in the linked issue context of a pull request.

    Args:
        repository: Owner/name repository string.
        number: Pull request number.

    Returns:
        Canonical scope-fence labels detected in the pull request and linked
        issue text, or an empty list when the context is unavailable.
    """
    owner, name = _repository_parts(repository)
    pull = _github_read(f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{number}")
    text = ""
    if isinstance(pull, dict):
        text = f"{pull.get('title') or ''} {pull.get('body') or ''}"
    for linked in sorted(_linked_references(text, number)):
        issue = _fetch_issue(repository, linked, best_effort=True)
        if issue is None:
            continue
        text = f"{text}\n{issue.get('title') or ''}\n{issue.get('body') or ''}"
    return _scope_fences(text)


def _validate_publish_grounding(payload: dict[str, object]) -> None:
    """Ground a public publication in the merged diff and linked issue context.

    The checks only block on positive evidence: a detected scope fence in the
    linked issue context, or a reader capability claim in copy whose merged diff
    changes no reader-reachable surface. Both escape hatches require the model
    to record contradicting evidence in provenance.

    Args:
        payload: Validated release payload marked public and published.

    Returns:
        None.

    Raises:
        SystemExit: When detected evidence contradicts a public publication.
    """
    if payload.get("visibility") != "public" or payload.get("status") != "published":
        return
    repository = str(payload["source_repository"])
    number = payload["source_pr_number"]
    if not isinstance(number, int) or isinstance(number, bool):
        return
    provenance = payload["provenance_json"]
    if not isinstance(provenance, dict):
        return
    contradicting = provenance.get("contradicting_evidence")
    documented = isinstance(contradicting, list) and any(
        isinstance(item, str) and item.strip() for item in contradicting
    )
    if documented:
        return
    fences = _linked_scope_fences(repository, number)
    if fences:
        _fail(
            "linked issue context contains decisive scope fences "
            f"({', '.join(fences)}); classify this change as internal or record "
            "provenance_json.contradicting_evidence with the shipped reader path"
        )
    claim_field = _capability_claim(payload)
    if claim_field is None:
        return
    changed = _changed_files(repository, number)
    if not changed:
        return
    filenames = [str(item.get("filename") or "") for item in changed]
    if any(name.startswith(_READER_SURFACE_PREFIXES) for name in filenames):
        return
    _fail(
        f"{claim_field} promises a new reader capability but the merged diff changes "
        "no reader-facing product surface; classify this change as internal or record "
        "provenance_json.contradicting_evidence with the shipped reader path"
    )


def _check(repository: str, pr_number: str, merge_sha: str) -> None:
    try:
        pr = int(pr_number)
    except ValueError:
        _fail("PR number must be an integer")
    query = urllib.parse.urlencode(
        {
            "source_repository": repository,
            "source_pr_number": pr,
            "source_merge_sha": merge_sha,
        }
    )
    result = _request("GET", f"{_api_base()}/source?{query}")
    print(json.dumps(result, separators=(",", ":")))


def _recent(repository: str, raw_limit: str) -> None:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        _fail("repository must use owner/name form")
    try:
        limit = int(raw_limit)
    except ValueError:
        _fail("recent limit must be an integer")
    if not 1 <= limit <= 100:
        _fail("recent limit must be between 1 and 100")

    owner, name = (urllib.parse.quote(part, safe="") for part in parts)
    merged: list[dict[str, object]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "state": "closed",
                "base": "main",
                "per_page": 100,
                "page": page,
            }
        )
        result = _github_request(
            f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls?{query}"
        )
        if not isinstance(result, list):
            _fail("GitHub pulls response must be a list")
        if page > 100 and result:
            _fail("GitHub pull pagination exceeded safety bound")
        for item in result:
            if not isinstance(item, dict):
                continue
            number = item.get("number")
            merged_at = item.get("merged_at")
            merge_sha = item.get("merge_commit_sha")
            title = item.get("title")
            if (
                isinstance(number, int)
                and isinstance(merged_at, str)
                and isinstance(merge_sha, str)
                and isinstance(title, str)
            ):
                merged.append(
                    {
                        "number": number,
                        "merged_at": merged_at,
                        "merge_commit_sha": merge_sha,
                        "title": title,
                    }
                )
        if len(result) < 100:
            break
        page += 1

    merged.sort(key=lambda item: str(item["merged_at"]), reverse=True)
    print(json.dumps(merged[:limit], separators=(",", ":")))


def _repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        _fail("repository must use owner/name form")
    return (urllib.parse.quote(parts[0], safe=""), urllib.parse.quote(parts[1], safe=""))


def _pr_number(raw_number: str) -> int:
    try:
        number = int(raw_number)
    except ValueError:
        _fail("PR number must be an integer")
    if number < 1:
        _fail("PR number must be a positive integer")
    return number


def _fetch_pull(repository: str, number: int) -> dict[str, object]:
    owner, name = _repository_parts(repository)
    result = _github_request(f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{number}")
    if not isinstance(result, dict):
        _fail("GitHub pull response must be an object")
    return result


def _fetch_issue(
    repository: str, number: int, *, best_effort: bool = False
) -> dict[str, object] | None:
    """Fetch issue details from GitHub API.

    A deleted issue (HTTP 404) yields None so a stale reference cannot abort
    context collection; other API failures still fail unless best_effort.

    Args:
        repository: Owner/name repository string.
        number: Issue number to fetch.
        best_effort: When True, an unreachable issue yields None instead of
            failing so publish-time grounding cannot be blocked by an outage.

    Returns:
        Dict with issue details including number, title, body, state, and labels,
        or None when the referenced issue is unavailable.
    """
    owner, name = _repository_parts(repository)
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{name}/issues/{number}"
    result = _github_read(url) if best_effort else _github_request(url, missing_ok=True)
    if result is None:
        return None
    if not isinstance(result, dict):
        if best_effort:
            return None
        _fail("GitHub issue response must be an object")
    return result


def _pr(repository: str, raw_number: str) -> None:
    number = _pr_number(raw_number)
    pull = _fetch_pull(repository, number)
    user = pull.get("user")
    print(
        json.dumps(
            {
                "number": pull.get("number"),
                "title": pull.get("title"),
                "body": pull.get("body"),
                "state": pull.get("state"),
                "merged": pull.get("merged"),
                "merged_at": pull.get("merged_at"),
                "merge_commit_sha": pull.get("merge_commit_sha"),
                "html_url": pull.get("html_url"),
                "author": user.get("login") if isinstance(user, dict) else None,
            },
            separators=(",", ":"),
        )
    )


def _files(repository: str, raw_number: str) -> None:
    number = _pr_number(raw_number)
    owner, name = _repository_parts(repository)
    query = urllib.parse.urlencode({"per_page": 100})
    result = _github_request(
        f"{_GITHUB_API_BASE}/repos/{owner}/{name}/pulls/{number}/files?{query}"
    )
    if not isinstance(result, list):
        _fail("GitHub pull files response must be a list")
    files = []
    for item in result:
        if not isinstance(item, dict):
            continue
        files.append(
            {
                "filename": item.get("filename"),
                "status": item.get("status"),
                "additions": item.get("additions"),
                "deletions": item.get("deletions"),
            }
        )
    print(json.dumps(files, separators=(",", ":")))


def _preceding_word(text: str, position: int) -> str:
    """Return the last whitespace-delimited word before a match position.

    Args:
        text: The full text being scanned.
        position: Character offset of the matched reference.

    Returns:
        The preceding word in lowercase, or an empty string when none exists.
    """
    prefix = text[:position].rstrip()
    if not prefix:
        return ""
    return prefix.split()[-1].lower().rstrip(".,;:)!?\\\"").lstrip("([{")


def _is_inside_version_delimiter(text: str, match_start: int) -> bool:
    """Return True when the issue number is immediately preceded by a delimited marker.

    The detected marker is a parenthesised or bracket-quoted version-step
    pattern such as '(v1.2)' or '[v4]'.

    The caller has already passed the basic word-based pre-filter; this check
    catches bracket-quoted tokens that the standard word splitter cannot see.

    Args:
        text: The full raw text being scanned.
        match_start: Character offset of the captured digit group (not the '#').

    Returns:
        True if the reference lies inside a delimited version-step marker.
    """
    pos = match_start
    while pos > 0 and text[pos - 1] == " ":
        pos -= 1
    while pos > 0 and text[pos - 1] in ")]}":
        pos -= 1
        closing_pos = pos
        depth = 1
        while pos > 0:
            pos -= 1
            ch = text[pos]
            if ch in ")]}":
                depth += 1
            elif ch in "([{":
                depth -= 1
                if depth == 0:
                    inner = text[pos + 1 : closing_pos].strip()
                    return bool(_VERSION_STEP_PATTERN.fullmatch(inner))
                break
    return False


def _preceding_words(text: str, position: int, count: int) -> tuple[str, ...]:
    """Return the last words before a match position in lowercase.

    Args:
        text: The full text being scanned.
        position: Character offset of the matched reference.
        count: Maximum number of words to return.

    Returns:
        Up to `count` preceding words, with the closest word last.
    """
    prefix = text[:position].rstrip()
    if not prefix:
        return ()
    return tuple(
        word.lower().rstrip(".,;:)!?\\\"").lstrip("([{")
        for word in prefix.split()[-count:]
    )


def _relationship_hints(text: str, position: int) -> str:
    """Classify how a referenced issue relates to the text that cites it.

    Args:
        text: The full text being scanned.
        position: Character offset of the matched reference.

    Returns:
        One of parent, dependency, follow-up, related, or referenced.
    """
    window = text[:position].rstrip()[-_RELATIONSHIP_WINDOW:]
    for pattern, relationship in _RELATIONSHIP_HINTS:
        if pattern.search(window):
            return relationship
    return "referenced"


def _linked_references(text: str, own_number: int) -> dict[int, str]:
    """Return linked issue numbers in the text with their relationship hint.

    Ordinal step markers and version-step markers are filtered out so that
    '#3' inside 'Step #3' or '[v4] #5' is never treated as an issue reference.

    Args:
        text: Pull request or issue text to scan.
        own_number: Pull request number that must not reference itself.

    Returns:
        Mapping of referenced issue number to relationship hint.
    """
    references: dict[int, str] = {}
    for match in _ISSUE_REFERENCE_PATTERN.finditer(text):
        preceding = _preceding_word(text, match.start())
        if preceding in _ORDINAL_INDICATORS or _VERSION_STEP_PATTERN.fullmatch(preceding):
            continue
        if _is_inside_version_delimiter(text, match.start()):
            continue
        referenced = int(match.group(1))
        if referenced != own_number:
            references.setdefault(referenced, _relationship_hints(text, match.start()))
    return references


def _scope_fences(text: str) -> list[str]:
    """Return canonical scope-fence labels present in the supplied text.

    Args:
        text: Issue or pull request text that may fence the user-facing scope.

    Returns:
        Sorted unique scope-fence labels found in the text.
    """
    found = {
        label
        for pattern, label in _SCOPE_FENCE_PATTERNS
        if pattern.search(_visible_release_text(text))
    }
    return sorted(found)


def _issue_labels(issue: dict[str, object]) -> list[str]:
    """Return the label names of one GitHub issue in a bounded shape.

    Args:
        issue: Decoded GitHub issue payload.

    Returns:
        Non-empty label names in API order.
    """
    raw = issue.get("labels")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for label in raw:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _issue_context(issue: dict[str, object], own_number: int) -> dict[str, object]:
    """Return the bounded classification context for one linked issue.

    Args:
        issue: Decoded GitHub issue payload.
        own_number: Issue number of the issue being described.

    Returns:
        Bounded issue context including detected scope fences and relationships.
    """
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    references = _linked_references(f"{title} {body}", own_number)
    return {
        "number": issue.get("number"),
        "title": title,
        "state": issue.get("state"),
        "labels": _issue_labels(issue),
        "body": body[:_MAX_ISSUE_BODY],
        "body_truncated": len(body) > _MAX_ISSUE_BODY,
        "scope_fences": _scope_fences(f"{title}\n{body}"),
        "references": [
            {"number": referenced, "relationship": references[referenced]}
            for referenced in sorted(references)[:_MAX_ISSUE_REFERENCES]
        ],
    }


def _issues(repository: str, raw_number: str) -> None:
    """Print the linked issue context used to classify one pull request.

    Each entry carries the issue number, title, state, labels, bounded body,
    deterministically detected scope fences, and parent/dependency references so
    a weak model can read the decisive scope fence instead of only a number.

    Args:
        repository: Owner/name repository string.
        raw_number: Pull request number string.

    Returns:
        None (prints JSON to stdout).
    """
    number = _pr_number(raw_number)
    pull = _fetch_pull(repository, number)
    text = f"{pull.get('title') or ''} {pull.get('body') or ''}"
    references = _linked_references(text, number)
    issues: list[dict[str, object]] = []
    for issue_number in sorted(references)[:_MAX_ISSUE_REFERENCES]:
        issue = _fetch_issue(repository, issue_number)
        if issue is None:
            issues.append({"number": issue_number, "unavailable": True})
            continue
        context = _issue_context(issue, issue_number)
        context["relationship"] = references[issue_number]
        issues.append(context)
    print(json.dumps(issues, separators=(",", ":")))


def _validate_internal_evidence(provenance: dict[str, object]) -> None:
    """Reject an internal classification that also claims reader-visible change.

    Args:
        provenance: Structured classification provenance for an internal record.

    Returns:
        None.

    Raises:
        SystemExit: When the internal classification contradicts reader evidence.
    """
    if provenance.get("reader_reachable") is not False:
        _fail("provenance_json.reader_reachable must be false for an internal record")
    if provenance.get("user_visible_evidence"):
        _fail(
            "provenance_json.user_visible_evidence must be empty for an internal record; "
            "reader-visible evidence belongs in a public classification"
        )
    _provenance_issue_numbers(provenance)
    _provenance_string_list(provenance, "scope_fences")
    _provenance_string_list(provenance, "contradicting_evidence")


def _skip(raw: str) -> None:
    """Record a durable internal classification for one merged pull request.

    Args:
        raw: JSON skip payload supplied on the command line.

    Returns:
        None (prints the recorded classification to stdout).

    Raises:
        SystemExit: When the skip payload is malformed or self-contradictory.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"invalid skip JSON: {exc}")
    required = {"source_repository", "source_pr_number", "source_merge_sha", "merged_at", "reason"}
    optional = {"inspected_issue_numbers", "scope_fences", "user_visible_evidence"}
    if not isinstance(payload, dict) or required - payload.keys():
        _fail("skip payload is missing required fields")
    if set(payload) - (required | optional):
        _fail("skip payload contains unsupported fields")
    merged_at = _parse_timestamp(payload["merged_at"], "merged_at")
    reason = payload["reason"]
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        _fail("skip reason must be non-empty and at most 500 characters")
    provenance: dict[str, object] = {
        "classification": "internal",
        "reason": reason,
        "reader_reachable": False,
        "user_visible_evidence": payload.get("user_visible_evidence", ""),
        "inspected_issue_numbers": payload.get("inspected_issue_numbers", []),
        "scope_fences": payload.get("scope_fences", []),
        "contradicting_evidence": [],
    }
    _validate_internal_evidence(provenance)

    internal_release = _validate_release(
        json.dumps(
            {
                "source_repository": payload["source_repository"],
                "source_pr_number": payload["source_pr_number"],
                "source_merge_sha": payload["source_merge_sha"],
                "merged_at": merged_at,
                "released_at": merged_at,
                "category": "Internal",
                "title": f"Internal change (PR #{payload['source_pr_number']})",
                "summary": reason,
                "visibility": "internal",
                "status": "published",
                "sort_order": 0,
                "provenance_json": provenance,
            }
        )
    )
    result = _request("PUT", _api_base() + "/", internal_release)
    print(
        json.dumps(
            {"classification": "internal", "skipped": True, "recorded": True, "release": result},
            separators=(",", ":"),
        )
    )


def _retract(repository: str, raw_pr_number: str, merge_sha: str) -> None:
    """Retract one broken or placeholder public release by source identity.

    Args:
        repository: Owner/name repository containing the source pull request.
        raw_pr_number: Source pull request number.
        merge_sha: Source merge commit SHA.

    Returns:
        None.
    """
    number = _pr_number(raw_pr_number)
    query = urllib.parse.urlencode(
        {
            "source_repository": repository,
            "source_pr_number": number,
            "source_merge_sha": merge_sha,
        }
    )
    source = _request("GET", f"{_api_base()}/source?{query}")
    release = source.get("release")
    if not source.get("exists") or not isinstance(release, dict) or "id" not in release:
        _fail("no release ledger record exists for this source identity")
    release_id = release["id"]
    result = _request("POST", f"{_api_base()}/{release_id}/retract")
    print(
        json.dumps(
            {"retracted": True, "release": result},
            separators=(",", ":"),
        )
    )


def main() -> None:
    """Run the release-writer command-line interface.

    Args:
        None.

    Returns:
        None.
    """
    if len(sys.argv) < 2:
        _fail("usage: release_writer.py check|recent|publish|skip|retract|pr|files|issues ...")
    command = sys.argv[1]
    if command == "check" and len(sys.argv) == 5:
        _check(sys.argv[2], sys.argv[3], sys.argv[4])
        return
    if command == "recent" and len(sys.argv) == 4:
        _recent(sys.argv[2], sys.argv[3])
        return
    if command == "publish" and len(sys.argv) == 3:
        payload = _validate_release(sys.argv[2])
        _validate_publish_grounding(payload)
        result = _request("PUT", _api_base() + "/", payload)
        print(json.dumps({"published": True, "release": result}, separators=(",", ":")))
        return
    if command == "skip" and len(sys.argv) == 3:
        _skip(sys.argv[2])
        return
    if command == "retract" and len(sys.argv) == 5:
        _retract(sys.argv[2], sys.argv[3], sys.argv[4])
        return
    if command == "pr" and len(sys.argv) == 4:
        _pr(sys.argv[2], sys.argv[3])
        return
    if command == "files" and len(sys.argv) == 4:
        _files(sys.argv[2], sys.argv[3])
        return
    if command == "issues" and len(sys.argv) == 4:
        _issues(sys.argv[2], sys.argv[3])
        return
    _fail("invalid release_writer.py arguments")


if __name__ == "__main__":
    main()
