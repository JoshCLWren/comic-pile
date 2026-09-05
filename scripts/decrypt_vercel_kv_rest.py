#!/usr/bin/env python3
"""Decrypt production Vercel KV REST credentials for the cache latency benchmark.

``vercel env pull`` writes ``[SENSITIVE]`` for marketplace KV secrets, so the
Cache Latency Benchmark runner cannot treat that file as a credential source.
This helper uses the Deploy Production ``VERCEL_TOKEN`` against the Vercel REST
API to fetch decrypted values and write them to a runner-local dotenv that must
never be uploaded as an artifact, committed, or printed.

Mapped keys (``REDIS_URL`` is ignored — that is the RESP/local path):

- ``KV_REST_API_URL`` → ``--upstash-url``
- ``KV_REST_API_TOKEN`` → ``--upstash-token`` (read-write preferred)
- ``KV_REST_API_READ_ONLY_TOKEN`` → GET-only fallback when the write token is
  missing or still redacted
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

API_BASE: Final = "https://api.vercel.com"
KV_URL_KEY: Final = "KV_REST_API_URL"
KV_TOKEN_KEY: Final = "KV_REST_API_TOKEN"
KV_READ_ONLY_TOKEN_KEY: Final = "KV_REST_API_READ_ONLY_TOKEN"
IGNORED_KEYS: Final = frozenset({"REDIS_URL"})
WANTED_KEYS: Final = (KV_URL_KEY, KV_TOKEN_KEY, KV_READ_ONLY_TOKEN_KEY)
PLACEHOLDER_VALUES: Final = frozenset(
    {
        "",
        "[SENSITIVE]",
        "<redacted>",
        "redacted",
        "undefined",
        "null",
    }
)
REQUEST_TIMEOUT_SECONDS: Final = 30.0


def is_usable_secret(value: str | None) -> bool:
    """Return whether ``value`` is a real secret rather than a pull placeholder.

    Args:
        value: Candidate environment value, or ``None`` when the key is absent.

    Returns:
        ``True`` when the value can be passed to the Upstash REST client.
    """
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return stripped.lower() not in PLACEHOLDER_VALUES and stripped != "[SENSITIVE]"


def env_targets_production(entry: Mapping[str, object]) -> bool:
    """Return whether a Vercel env record applies to the production target.

    Args:
        entry: One object from the project env list payload.

    Returns:
        ``True`` when ``target`` includes ``production`` or is unset (legacy).
    """
    target = entry.get("target")
    if target is None:
        return True
    if isinstance(target, str):
        return target == "production"
    if isinstance(target, Sequence) and not isinstance(target, (str, bytes)):
        return "production" in {str(item) for item in target}
    return False


def string_field(entry: Mapping[str, object], key: str) -> str | None:
    """Return a stripped string field from a Vercel env record.

    Args:
        entry: One object from the project env list or decrypt payload.
        key: Field name such as ``id``, ``key``, or ``value``.

    Returns:
        The stripped string, or ``None`` when the field is missing or empty.
    """
    raw = entry.get(key)
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None


def select_production_env_ids(envs: Sequence[Mapping[str, object]]) -> dict[str, str]:
    """Map wanted production key names to their Vercel env IDs.

    Args:
        envs: Project environment-variable records.

    Returns:
        ``{key_name: env_id}`` for production-targeted KV REST keys only.
    """
    selected: dict[str, str] = {}
    for entry in envs:
        key = string_field(entry, "key")
        env_id = string_field(entry, "id")
        if key is None or env_id is None:
            continue
        if key in IGNORED_KEYS or key not in WANTED_KEYS:
            continue
        if not env_targets_production(entry):
            continue
        selected[key] = env_id
    return selected


def collect_usable_values(envs: Sequence[Mapping[str, object]]) -> dict[str, str]:
    """Collect already-decrypted KV REST values from a list payload.

    Args:
        envs: Project environment-variable records, optionally decrypted.

    Returns:
        Usable ``{key_name: value}`` pairs. Placeholders are omitted.
    """
    values: dict[str, str] = {}
    for entry in envs:
        key = string_field(entry, "key")
        value = string_field(entry, "value")
        if key is None or key in IGNORED_KEYS or key not in WANTED_KEYS:
            continue
        if not env_targets_production(entry):
            continue
        if is_usable_secret(value) and value is not None:
            values[key] = value
    return values


def choose_kv_credentials(values: Mapping[str, str]) -> tuple[str | None, str | None, str]:
    """Pick the Upstash REST URL and preferred token from decrypted KV keys.

    Args:
        values: Usable decrypted production values keyed by Vercel env name.

    Returns:
        ``(url, token, token_source)`` where ``token_source`` is the Vercel key
        that supplied the token, or ``""`` when no usable token exists.
    """
    url = values.get(KV_URL_KEY)
    if url is not None and not is_usable_secret(url):
        url = None
    write_token = values.get(KV_TOKEN_KEY)
    read_token = values.get(KV_READ_ONLY_TOKEN_KEY)
    if is_usable_secret(write_token) and write_token is not None:
        return url, write_token, KV_TOKEN_KEY
    if is_usable_secret(read_token) and read_token is not None:
        return url, read_token, KV_READ_ONLY_TOKEN_KEY
    return url, None, ""


def quote_dotenv_value(value: str) -> str:
    """Quote a dotenv value so :func:`load_dotenv_values` can reload it.

    Args:
        value: Raw secret or URL.

    Returns:
        A double-quoted dotenv fragment with backslashes and quotes escaped.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_kv_dotenv(path: Path, url: str, token: str) -> None:
    """Write only the KV REST URL and chosen token to a mode-0600 dotenv file.

    Args:
        path: Destination path. Parent directories are created as needed.
        url: ``KV_REST_API_URL`` value.
        token: Preferred ``KV_REST_API_TOKEN`` or read-only fallback.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"{KV_URL_KEY}={quote_dotenv_value(url)}\n"
        f"{KV_TOKEN_KEY}={quote_dotenv_value(token)}\n"
    )
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)


def coverage_payload(
    listed_keys: Sequence[str],
    url: str | None,
    token: str | None,
    token_source: str,
    decrypt_method: str,
) -> dict[str, object]:
    """Build a secret-free coverage document for logs and artifacts.

    Args:
        listed_keys: Production env key names seen on the project.
        url: Decrypted REST URL, or ``None``.
        token: Decrypted REST token, or ``None``.
        token_source: Vercel key that supplied the token.
        decrypt_method: Which API path produced usable values.

    Returns:
        JSON-ready coverage mapping with booleans and key names only.
    """
    return {
        "listed_production_keys": sorted(listed_keys),
        "kv_rest_api_url_present": is_usable_secret(url),
        "kv_rest_api_token_present": is_usable_secret(token),
        "kv_token_source": token_source or None,
        "decrypt_method": decrypt_method,
        "redis_url_ignored": True,
    }


def _api_get(url: str, token: str) -> object:
    """GET a Vercel REST URL and return the decoded JSON body.

    Args:
        url: Absolute ``https://api.vercel.com/...`` URL.
        token: Bearer token (Deploy Production ``VERCEL_TOKEN``).

    Returns:
        The parsed JSON value.

    Raises:
        RuntimeError: When the request fails or the body is not JSON.
    """
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "comic-pile-cache-benchmark/kv-decrypt")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Vercel API HTTP {exc.code} for {urllib.parse.urlparse(url).path}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Vercel API request failed: {exc.reason}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Vercel API returned non-JSON") from exc


def list_project_envs(
    token: str,
    project_id: str,
    team_id: str,
    *,
    decrypt: bool,
) -> list[dict[str, object]]:
    """List project environment variables, optionally asking the API to decrypt.

    Args:
        token: Vercel bearer token.
        project_id: Project id (``prj_...``).
        team_id: Team id (``team_...``).
        decrypt: When ``True``, request decrypted values in the list payload.

    Returns:
        The ``envs`` array as a list of mappings.
    """
    query = urllib.parse.urlencode(
        {
            "teamId": team_id,
            "decrypt": "true" if decrypt else "false",
        }
    )
    payload = _api_get(f"{API_BASE}/v10/projects/{project_id}/env?{query}", token)
    if not isinstance(payload, dict):
        raise RuntimeError("Vercel env list payload was not an object")
    envs = payload.get("envs")
    if not isinstance(envs, list):
        raise RuntimeError("Vercel env list payload missing envs array")
    records: list[dict[str, object]] = []
    for item in envs:
        if isinstance(item, dict):
            records.append(item)
    return records


def decrypt_env_by_id(
    token: str,
    project_id: str,
    team_id: str,
    env_id: str,
) -> str | None:
    """Fetch the decrypted value of one project environment variable.

    Args:
        token: Vercel bearer token.
        project_id: Project id (``prj_...``).
        team_id: Team id (``team_...``).
        env_id: Environment-variable id from the list payload.

    Returns:
        The decrypted value when usable, otherwise ``None``.
    """
    query = urllib.parse.urlencode({"teamId": team_id})
    payload = _api_get(
        f"{API_BASE}/v1/projects/{project_id}/env/{env_id}?{query}",
        token,
    )
    if not isinstance(payload, dict):
        return None
    value = string_field(payload, "value")
    return value if is_usable_secret(value) else None


def decrypt_production_kv_rest(
    token: str,
    project_id: str,
    team_id: str,
) -> tuple[str | None, str | None, str, str, list[str]]:
    """Decrypt production KV REST credentials via list-decrypt then per-id GET.

    Args:
        token: Vercel bearer token.
        project_id: Project id (``prj_...``).
        team_id: Team id (``team_...``).

    Returns:
        ``(url, token, token_source, decrypt_method, listed_keys)``.
    """
    listed = list_project_envs(token, project_id, team_id, decrypt=False)
    listed_keys = sorted(
        {
            key
            for entry in listed
            if (key := string_field(entry, "key")) is not None and env_targets_production(entry)
        }
    )
    decrypted_list = list_project_envs(token, project_id, team_id, decrypt=True)
    values = collect_usable_values(decrypted_list)
    url, rest_token, token_source = choose_kv_credentials(values)
    if is_usable_secret(url) and is_usable_secret(rest_token):
        return url, rest_token, token_source, "list_decrypt", listed_keys

    ids = select_production_env_ids(listed)
    by_id: dict[str, str] = dict(values)
    for key, env_id in ids.items():
        if key in by_id:
            continue
        fetched = decrypt_env_by_id(token, project_id, team_id, env_id)
        if fetched is not None:
            by_id[key] = fetched
    url, rest_token, token_source = choose_kv_credentials(by_id)
    return url, rest_token, token_source, "project_env_by_id", listed_keys


def emit_github_masks(values: Sequence[str]) -> None:
    """Print GitHub Actions mask directives without other stdout noise.

    Args:
        values: Secrets that must be redacted if they later appear in logs.
    """
    seen: set[str] = set()
    for value in values:
        if not is_usable_secret(value) or value in seen:
            continue
        if len(value) < 3:
            continue
        seen.add(value)
        sys.stdout.write(f"::add-mask::{value}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the KV REST decrypt helper.

    Returns:
        The configured argument parser.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        help="Runner-local dotenv path. Never upload or commit this file.",
    )
    parser.add_argument(
        "--coverage",
        default=None,
        help="Optional secret-free JSON coverage path for logs/artifacts.",
    )
    parser.add_argument(
        "--github-mask",
        action="store_true",
        help="Print ::add-mask:: directives for decrypted values.",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("VERCEL_PROJECT_ID"),
        help="Vercel project id (default: VERCEL_PROJECT_ID).",
    )
    parser.add_argument(
        "--team-id",
        default=os.environ.get("VERCEL_ORG_ID"),
        help="Vercel team id (default: VERCEL_ORG_ID).",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("VERCEL_TOKEN"),
        help="Vercel bearer token (default: VERCEL_TOKEN). Never printed.",
    )
    return parser


def main() -> int:
    """Decrypt production KV REST credentials and write a runner-local dotenv.

    Returns:
        ``0`` when both URL and token were written, ``1`` when they were not.
    """
    args = build_parser().parse_args()
    if not args.token or not args.project_id or not args.team_id:
        print(
            "VERCEL_TOKEN, VERCEL_PROJECT_ID, and VERCEL_ORG_ID are required.",
            file=sys.stderr,
        )
        return 1
    try:
        url, rest_token, token_source, method, listed_keys = decrypt_production_kv_rest(
            args.token,
            args.project_id,
            args.team_id,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    coverage = coverage_payload(listed_keys, url, rest_token, token_source, method)
    if args.coverage:
        coverage_path = Path(args.coverage)
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_path.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(coverage, indent=2))

    if not is_usable_secret(url) or not is_usable_secret(rest_token):
        print(
            "Decrypted KV REST credentials were incomplete; Upstash will be skipped.",
            file=sys.stderr,
        )
        return 1
    if url is None or rest_token is None:
        return 1
    if args.github_mask:
        emit_github_masks([url, rest_token])
    write_kv_dotenv(Path(args.output), url, rest_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
