#!/usr/bin/env python3
"""Validate vercel.json against Vercel's official schema and plan-compatible policies.

This script fetches Vercel's official JSON schema from
``https://openapi.vercel.sh/vercel.json`` and validates the project's
``vercel.json`` against it. It also enforces explicit policy checks that the
schema alone cannot express:

- ``builds`` and ``functions`` may not be configured together.
- Cron schedules must be compatible with the project's Vercel Hobby tier,
  which allows at most one execution per day.

Usage::

    python scripts/validate_vercel_config.py [--vercel-json PATH] [--schema-url URL]

Exit code is 0 on success, 1 on any validation failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERCEL_JSON = ROOT / "vercel.json"
VERCEL_SCHEMA_URL = "https://openapi.vercel.sh/vercel.json"
SCHEMA_FETCH_TIMEOUT = 30
SCHEMA_FETCH_RETRIES = 3

HOBBY_CRON_MAX_DAILY_EXECUTIONS = 1

CRON_FIELD_SPECS: list[tuple[str, int, int]] = [
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day-of-month", 1, 31),
    ("month", 1, 12),
    ("day-of-week", 0, 7),  # 0 and 7 are both Sunday
]


class ValidationError(Exception):
    """A vercel.json validation error (schema or policy)."""


def fetch_vercel_schema(schema_url: str = VERCEL_SCHEMA_URL) -> dict[str, Any]:
    """Fetch the official Vercel JSON schema.

    Args:
        schema_url: URL of the Vercel JSON schema.

    Returns:
        The parsed schema as a dictionary.

    Raises:
        ValidationError: If the schema cannot be fetched or parsed after
            all retries are exhausted.
    """
    last_error: Exception | None = None
    for attempt in range(1, SCHEMA_FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(
                schema_url,
                headers={"User-Agent": "comic-pile-ci"},
            )
            with urllib.request.urlopen(req, timeout=SCHEMA_FETCH_TIMEOUT) as resp:
                data = json.loads(resp.read())
            return data
        except Exception as exc:
            last_error = exc
            if attempt < SCHEMA_FETCH_RETRIES:
                continue
    raise ValidationError(
        f"Failed to fetch Vercel schema from {schema_url} after "
        f"{SCHEMA_FETCH_RETRIES} attempts: {last_error}"
    )


def _validator_for_schema(schema: dict[str, Any]) -> jsonschema.Validator:
    """Return the appropriate jsonschema validator for the given schema."""
    validator_cls = jsonschema.validators.validator_for(schema)
    return validator_cls(schema)


def validate_schema(
    config: dict[str, Any], schema: dict[str, Any]
) -> list[str]:
    """Validate ``config`` against the Vercel JSON schema.

    Args:
        config: The parsed vercel.json configuration.
        schema: The Vercel JSON schema.

    Returns:
        A list of human-readable schema violation messages (empty if valid).
    """
    validator = _validator_for_schema(schema)
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
    messages: list[str] = []
    for error in errors:
        path = "/".join(str(p) for p in error.absolute_path) or "(root)"
        messages.append(f"Schema violation at '{path}': {error.message}")
    return messages


def check_builds_functions_compat(config: dict[str, Any]) -> list[str]:
    """Check that ``builds`` and ``functions`` are not configured together.

    Vercel does not allow the legacy ``builds`` and the newer ``functions``
    configuration to be used in the same ``vercel.json``.

    Args:
        config: The parsed vercel.json configuration.

    Returns:
        A list of error messages (empty if compatible).
    """
    errors: list[str] = []
    if "builds" in config and "functions" in config:
        errors.append(
            "Cannot configure both 'builds' and 'functions' in vercel.json. "
            "Vercel does not allow these to be used together."
        )
    return errors


def parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into the set of matching integer values.

    Supports ``*``, ranges (``A-B``), steps (``*/N``, ``A-B/N``, ``A/N``),
    and comma-separated lists.

    Args:
        field: The raw cron field string (e.g. ``"*/10"``, ``"0"``, ``"0-5"``).
        min_val: The minimum valid value for this field.
        max_val: The maximum valid value for this field.

    Returns:
        A set of integers that the field matches.
    """
    result: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            result.update(range(min_val, max_val + 1))
        elif "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"Invalid step value: {step}")
            if base == "*":
                result.update(
                    v
                    for v in range(min_val, max_val + 1)
                    if (v - min_val) % step == 0
                )
            elif "-" in base:
                lo_str, hi_str = base.split("-", 1)
                lo, hi = int(lo_str), int(hi_str)
                result.update(
                    v for v in range(lo, hi + 1) if (v - lo) % step == 0
                )
            else:
                start = int(base)
                result.update(
                    v
                    for v in range(start, max_val + 1)
                    if (v - start) % step == 0
                )
        elif "-" in part:
            lo_str, hi_str = part.split("-", 1)
            result.update(range(int(lo_str), int(hi_str) + 1))
        else:
            result.add(int(part))
    return {v for v in result if min_val <= v <= max_val}


def count_daily_executions(schedule: str) -> int:
    """Count how many times a cron schedule fires per day.

    Args:
        schedule: A 5-field cron expression (minute hour dom month dow).

    Returns:
        The number of executions per day, or 0 if the schedule is malformed.
    """
    fields = schedule.split()
    if len(fields) != 5:
        return 0
    try:
        _, min_min, max_min = CRON_FIELD_SPECS[0]
        _, min_hour, max_hour = CRON_FIELD_SPECS[1]
        minutes = parse_cron_field(fields[0], min_min, max_min)
        hours = parse_cron_field(fields[1], min_hour, max_hour)
    except (ValueError, IndexError):
        return 0
    return len(minutes) * len(hours)


def check_hobby_cron(config: dict[str, Any]) -> list[str]:
    """Check that cron schedules are compatible with the Hobby tier.

    The project is on Vercel's Hobby (free) plan, which allows cron schedules
    to run at most once per day.

    Args:
        config: The parsed vercel.json configuration.

    Returns:
        A list of error messages (empty if all crons are Hobby-compatible).
    """
    errors: list[str] = []
    crons = config.get("crons", [])
    if not isinstance(crons, list):
        return errors
    for cron in crons:
        if not isinstance(cron, dict):
            continue
        schedule = cron.get("schedule")
        if not isinstance(schedule, str):
            continue
        count = count_daily_executions(schedule)
        if count > HOBBY_CRON_MAX_DAILY_EXECUTIONS:
            errors.append(
                f"Cron schedule '{schedule}' fires {count} times per day, "
                f"which exceeds the Hobby tier limit of "
                f"{HOBBY_CRON_MAX_DAILY_EXECUTIONS} execution per day."
            )
    return errors


def validate_config(
    config: dict[str, Any],
    schema: dict[str, Any],
) -> list[str]:
    """Run all validation checks against a vercel.json configuration.

    Args:
        config: The parsed vercel.json configuration.
        schema: The Vercel JSON schema (fetched from Vercel's public endpoint).

    Returns:
        A list of all validation error messages (empty if valid).
    """
    errors: list[str] = []
    errors.extend(validate_schema(config, schema))
    errors.extend(check_builds_functions_compat(config))
    errors.extend(check_hobby_cron(config))
    return errors


def main() -> None:
    """CLI entry point for validating vercel.json."""
    parser = argparse.ArgumentParser(
        description="Validate vercel.json against Vercel's schema and policies."
    )
    parser.add_argument(
        "--vercel-json",
        type=Path,
        default=DEFAULT_VERCEL_JSON,
        help="Path to vercel.json (default: repo-root vercel.json)",
    )
    parser.add_argument(
        "--schema-url",
        default=VERCEL_SCHEMA_URL,
        help="URL of the Vercel JSON schema",
    )
    args = parser.parse_args()

    config_path: Path = args.vercel_json
    if not config_path.exists():
        print(f"ERROR: vercel.json not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: Failed to parse {config_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        schema = fetch_vercel_schema(args.schema_url)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    errors = validate_config(config, schema)
    if errors:
        print("vercel.json validation FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)

    print("vercel.json validation PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
