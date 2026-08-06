#!/usr/bin/env python3
"""Append one production performance sample and summarize regressions."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import TypedDict, cast


class Sample(TypedDict):
    """Stored production performance sample."""

    capturedAt: str
    deploymentId: str
    runAttempt: str
    classification: str
    documentResponseMs: int
    shellReadyMs: int
    firstApiResponseMs: int
    queueReadyMs: int
    firstApiPath: str | None
    firstApiStatus: int | None
    serverTiming: str | None


METRICS = (
    "documentResponseMs",
    "shellReadyMs",
    "firstApiResponseMs",
    "queueReadyMs",
)
CLASSIFICATIONS = {"cold", "warm", "unknown"}
MAX_HISTORY = 240
REGRESSION_RATIO = 1.35
MIN_REGRESSION_MS = 250


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args()


def validate_sample(payload: object) -> Sample:
    """Validate and narrow one decoded performance record.

    Args:
        payload: Decoded JSON value.

    Returns:
        Fully validated sample.

    Raises:
        ValueError: If the value is not a complete valid sample.
    """
    if not isinstance(payload, dict):
        raise ValueError("Performance sample must be a JSON object")

    required_string_fields = ("capturedAt", "deploymentId", "runAttempt")
    for key in required_string_fields:
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ValueError(f"Invalid required string field: {key}")

    classification = payload.get("classification")
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"Invalid classification: {classification!r}")

    for metric in METRICS:
        value = payload.get(metric)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Invalid non-negative integer metric: {metric}")

    first_api_path = payload.get("firstApiPath")
    if first_api_path is not None and not isinstance(first_api_path, str):
        raise ValueError("firstApiPath must be a string or null")

    first_api_status = payload.get("firstApiStatus")
    if first_api_status is not None and (
        isinstance(first_api_status, bool)
        or not isinstance(first_api_status, int)
        or not 100 <= first_api_status <= 599
    ):
        raise ValueError("firstApiStatus must be an HTTP status or null")

    server_timing = payload.get("serverTiming")
    if server_timing is not None and not isinstance(server_timing, str):
        raise ValueError("serverTiming must be a string or null")

    return cast(Sample, payload)


def load_sample(path: Path) -> Sample:
    """Load and validate one probe sample.

    Args:
        path: JSON sample path.

    Returns:
        Validated sample.
    """
    return validate_sample(json.loads(path.read_text(encoding="utf-8")))


def load_history(path: Path) -> list[Sample]:
    """Load and validate JSON-lines history if present.

    Args:
        path: History path.

    Returns:
        Validated samples.
    """
    if not path.exists():
        return []

    samples: list[Sample] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        try:
            samples.append(validate_sample(json.loads(line)))
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid history record on line {line_number}: {error}") from error
    return samples


def baseline(history: list[Sample], sample: Sample, metric: str) -> float | None:
    """Return median baseline for the sample classification.

    Args:
        history: Previous samples.
        sample: Current sample.
        metric: Metric field.

    Returns:
        Median of up to 20 comparable samples, or None.
    """
    comparable = [
        int(item[metric])
        for item in history
        if item["classification"] == sample["classification"]
    ][-20:]
    return statistics.median(comparable) if comparable else None


def build_summary(history: list[Sample], sample: Sample) -> str:
    """Build a human-readable Markdown comparison.

    Args:
        history: Previous samples.
        sample: Current sample.

    Returns:
        Markdown summary.
    """
    lines = [
        "## Production performance",
        "",
        f"Deployment: `{sample['deploymentId']}`",
        f"Classification: `{sample['classification']}`",
        "",
        "| Metric | Current | Baseline | Result |",
        "|---|---:|---:|---|",
    ]
    regressions = 0
    for metric in METRICS:
        current = int(sample[metric])
        prior = baseline(history, sample, metric)
        if prior is None:
            result = "baseline pending"
            prior_text = "n/a"
        else:
            delta = current - prior
            is_regression = current >= prior * REGRESSION_RATIO and delta >= MIN_REGRESSION_MS
            result = "REGRESSION" if is_regression else "ok"
            regressions += int(is_regression)
            prior_text = f"{prior:.0f} ms"
        lines.append(f"| `{metric}` | {current} ms | {prior_text} | {result} |")
    lines.extend(["", f"Regression count: **{regressions}**"])
    return "\n".join(lines) + "\n"


def main() -> None:
    """Append the current sample and write comparison output.

    Args:
        None.

    Returns:
        None.
    """
    args = parse_args()
    sample = load_sample(args.sample)
    history = load_history(args.history)
    summary = build_summary(history, sample)
    retained = (history + [sample])[-MAX_HISTORY:]
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(
        "".join(f"{json.dumps(item, separators=(',', ':'))}\n" for item in retained),
        encoding="utf-8",
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
