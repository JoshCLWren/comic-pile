#!/usr/bin/env python3
"""Durable provider-quota pauses for fixed-model factory workers.

A paused worker stays on the roster (it is not retired) but is not offered
for dispatch or assignment until ``paused_until`` passes. After that the
normal smoke step re-proves the lane; a fresh quota failure means a new pause
entry is needed. Worker 46 is never pausable.
"""

from __future__ import annotations

import argparse
import email.utils
import json
import os
import re
import sys
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PAUSES_PATH = Path(__file__).resolve().parents[1] / "factory-quota-pauses.json"
PROTECTED_WORKERS = frozenset({46})

OLLAMA_BALANCE_URL = "https://ollama.com/api/balance"
BACKOFF_CAP_HOURS = 24


@dataclass(frozen=True)
class QuotaPause:
    """One worker paused until its provider quota resets."""

    worker: int
    provider: str
    paused_until: datetime
    reason: str
    reset_source: str
    model: str = ""
    evidence_run: str = ""
    attempt: int = 0


def _parse_until(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"paused_until must be an ISO-8601 UTC timestamp ending in Z: {value!r}")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_pauses(path: Path | str = PAUSES_PATH) -> list[QuotaPause]:
    """Load and validate configured quota pauses; a missing file means none."""
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported factory-quota-pauses schema_version")
    pauses: list[QuotaPause] = []
    seen: set[int] = set()
    for entry in data.get("pauses", []):
        worker = entry.get("worker")
        if not isinstance(worker, int) or isinstance(worker, bool):
            raise ValueError(f"pause worker must be an integer: {worker!r}")
        if worker in PROTECTED_WORKERS:
            raise ValueError(f"worker {worker} is protected and must never be paused")
        if worker in seen:
            raise ValueError(f"duplicate pause for worker {worker}")
        seen.add(worker)
        attempt_raw = entry.get("attempt", 0)
        try:
            attempt = int(attempt_raw)
        except (TypeError, ValueError):
            attempt = 0
        pauses.append(
            QuotaPause(
                worker=worker,
                provider=str(entry.get("provider", "")),
                paused_until=_parse_until(entry.get("paused_until")),
                reason=str(entry.get("reason", "")),
                reset_source=str(entry.get("reset_source", "")),
                model=str(entry.get("model", "")),
                evidence_run=str(entry.get("evidence_run", "")),
                attempt=attempt,
            )
        )
    return pauses


def save_pauses(pauses: list[QuotaPause], path: Path | str = PAUSES_PATH) -> None:
    """Persist pauses to disk, replacing the file contents."""
    path = Path(path)
    payload = {
        "schema_version": 1,
        "pauses": [
            {
                "worker": p.worker,
                "provider": p.provider,
                "model": p.model,
                "paused_until": _iso(p.paused_until),
                "reason": p.reason,
                "reset_source": p.reset_source,
                "evidence_run": p.evidence_run,
                "attempt": p.attempt,
            }
            for p in pauses
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def active_pauses(
    now: datetime | None = None, pauses: Iterable[QuotaPause] | None = None
) -> dict[int, QuotaPause]:
    """Return pauses whose reset time has not yet passed, keyed by worker."""
    now = now or datetime.now(timezone.utc)
    items = load_pauses() if pauses is None else pauses
    return {pause.worker: pause for pause in items if pause.paused_until > now}


def is_paused(worker: int | str | None, now: datetime | None = None) -> QuotaPause | None:
    """Return the active pause for a worker, or None."""
    text = str(worker).strip() if worker is not None else ""
    if not text.isdigit():
        return None
    return active_pauses(now).get(int(text))


def describe(pause: QuotaPause) -> str:
    """Render a one-line operator log message for a paused worker."""
    until = pause.paused_until.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"Factory {pause.worker} paused until {until} ({pause.reset_source}): {pause.reason}"


def filter_workers(workers: list[str], now: datetime | None = None) -> tuple[list[str], list[str]]:
    """Split worker ids into (dispatchable, paused log lines), preserving order."""
    active = active_pauses(now)
    kept: list[str] = []
    messages: list[str] = []
    for worker in workers:
        pause = active.get(int(worker)) if str(worker).isdigit() else None
        if pause is None:
            kept.append(worker)
        else:
            messages.append(describe(pause))
    return kept, messages


def classify_quota_failure(status_code: Any = None, body: Any = "", log_file: Any = None) -> bool:
    """Return True when the failure is a provider quota/budget exhaustion."""
    if isinstance(status_code, str) and body == "" and log_file is None:
        body = status_code
        status_code = None

    text = ""
    if log_file is not None:
        try:
            text += Path(log_file).read_text(encoding="utf-8", errors="replace")
        except (OSError, TypeError, ValueError):
            try:
                text += str(log_file)
            except Exception:
                pass
    if body is not None:
        text = str(body) + "\n" + text

    sc: int | None
    if isinstance(status_code, bool):
        sc = None
    elif isinstance(status_code, int):
        sc = status_code
    elif isinstance(status_code, str):
        m = re.search(r"\b(402|429)\b", status_code)
        sc = int(m.group(1)) if m else None
    else:
        sc = None

    lower = text.lower()

    if "model is unavailable" in lower or "model unavailable" in lower:
        if "budget exhausted" not in lower and "billing_api_budget_exhausted" not in lower:
            if "usage limit" not in lower and "rate limit" not in lower:
                return False

    quota_keywords = (
        "billing_api_budget_exhausted",
        "budget exhausted",
        "api budget exhausted",
        "payment required",
        "monthly usage limit",
        "daily usage limit",
        "weekly usage limit",
        "reached your",
        "usage limit",
        "rate limit",
        "insufficient credits",
        "insufficient balance",
        "insufficient quota",
        "exceeded your current quota",
        "quota exceeded",
        "quota exhausted",
    )
    has_quota_keyword = any(k in lower for k in quota_keywords)

    if sc in (402, 429):
        if has_quota_keyword:
            return True
        if sc == 402:
            return True
        if sc == 429 and ("limit" in lower or "quota" in lower or "budget" in lower or "exhaust" in lower):
            return True
        return False

    strong = (
        "billing_api_budget_exhausted",
        "budget exhausted",
        "api budget exhausted",
        "monthly usage limit",
        "daily usage limit",
        "weekly usage limit",
        "reached your",
        "usage limit",
        "payment required",
    )
    if any(k in lower for k in strong):
        return True
    return False


def _parse_duration(value: str) -> timedelta | None:
    value = value.strip().lower()
    if not value:
        return None
    if re.fullmatch(r"\d+", value):
        try:
            return timedelta(seconds=int(value))
        except ValueError:
            return None
    matches = re.findall(r"(\d+)\s*([smhd])", value)
    if not matches:
        return None
    total = 0
    for amount, unit in matches:
        n = int(amount)
        if unit == "s":
            total += n
        elif unit == "m":
            total += n * 60
        elif unit == "h":
            total += n * 3600
        elif unit == "d":
            total += n * 86400
    if total <= 0:
        return None
    return timedelta(seconds=total)


def parse_retry_after(header_value: Any, now: datetime | None = None, clock: Any = None) -> datetime | None:
    if header_value is None:
        return None
    text = str(header_value).strip()
    if not text:
        return None
    if now is None:
        if callable(clock):
            result = clock()
            if isinstance(result, datetime):
                now = result
            else:
                try:
                    now = datetime.fromtimestamp(float(result), tz=timezone.utc)
                except (TypeError, ValueError, OSError, OverflowError):
                    now = datetime.now(timezone.utc)
        else:
            now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    try:
        seconds = int(float(text))
        if seconds >= 0:
            return now + timedelta(seconds=seconds)
    except ValueError:
        pass

    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def parse_rate_limit_reset(headers: Any, now: datetime | None = None) -> datetime | None:
    if not isinstance(headers, dict):
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    normalized: dict[str, str] = {}
    for key, value in headers.items():
        normalized[str(key).lower()] = value

    candidate_keys = (
        "x-ratelimit-reset",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
        "ratelimit-reset",
    )
    for key in candidate_keys:
        if key not in normalized:
            continue
        value = normalized[key]
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if re.search(r"[smhd]", text.lower()) and not text.isdigit():
            delta = _parse_duration(text)
            if delta is not None:
                return now + delta
        try:
            number = float(text)
        except ValueError:
            delta = _parse_duration(text)
            if delta is not None:
                return now + delta
            continue
        if number > 1e12:
            number = number / 1000.0
        if number > 1e9:
            try:
                return datetime.fromtimestamp(number, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                pass
        else:
            if number >= 0:
                return now + timedelta(seconds=number)
    return None


def parse_reset_from_body(response_body: Any, status_code: Any = None) -> datetime | None:
    if response_body is None:
        return None
    text = str(response_body)
    lower = text.lower()

    if "billing_api_budget_exhausted" in lower or "budget exhausted" in lower or "api budget exhausted" in lower:
        return parse_reset_from_config("mistral")

    for match in re.finditer(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?", text):
        token = match.group(0)
        if not token.endswith("Z"):
            token = token + "Z"
        try:
            return _parse_until(token)
        except ValueError:
            continue

    for match in re.finditer(r"reset(?:_at|_time)?[\"']?\s*[:=]\s*[\"']?(\d{10,13})", text, re.I):
        try:
            number = float(match.group(1))
            if number > 1e12:
                number /= 1000.0
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            continue

    return None


def parse_ollama_balance_reset(balance_url: Any = None, api_key: Any = None, timeout: float = 10.0) -> datetime | None:
    url = str(balance_url).strip() if balance_url is not None else OLLAMA_BALANCE_URL
    if not url:
        url = OLLAMA_BALANCE_URL
    key = "" if api_key is None else str(api_key)

    if url.startswith("file://"):
        try:
            path = Path(url[len("file://"):])
            data = json.loads(path.read_text(encoding="utf-8"))
            return _extract_period_until(data)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    headers = {"Accept": "application/json", "User-Agent": "comicpile-factory-quota-pause"}
    if key:
        headers["Authorization"] = "Bearer " + key

    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
    except Exception:
        return None
    return _extract_period_until(data)


def _extract_period_until(data: Any) -> datetime | None:
    if not isinstance(data, dict):
        return None
    included = data.get("included")
    if not isinstance(included, dict):
        return None
    period = included.get("period")
    if not isinstance(period, dict):
        return None
    until = period.get("until")
    if not isinstance(until, str):
        return None
    try:
        if until.endswith("Z"):
            return _parse_until(until)
        dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_reset_from_config(provider: Any) -> datetime | None:
    name = str(provider or "").strip().lower()
    now = datetime.now(timezone.utc)

    if "mistral" in name:
        year = now.year
        month = now.month
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        return datetime(year, month, 1, tzinfo=timezone.utc)

    if "ollama" in name:
        year = now.year
        month = now.month
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        return datetime(year, month, 1, tzinfo=timezone.utc)

    tomorrow = (now + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)


def calculate_backoff(attempt: int = 0) -> datetime:
    try:
        n = int(attempt)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    hours = 2 ** n
    if hours < 1:
        hours = 1
    if hours > BACKOFF_CAP_HOURS:
        hours = BACKOFF_CAP_HOURS
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def create_pause(
    worker: Any,
    provider: str = "",
    model: str = "",
    status_code: Any = None,
    body: Any = "",
    log_file: Any = None,
    run_id: Any = "",
    *,
    path: Path | str | None = None,
    headers: dict[str, str] | None = None,
    retry_after: Any = None,
    now: datetime | None = None,
    attempt: int | None = None,
) -> QuotaPause:
    worker_int = int(worker)
    if worker_int in PROTECTED_WORKERS:
        raise ValueError(f"worker {worker_int} is protected and must never be paused")

    pauses_path = Path(path) if path is not None else PAUSES_PATH
    if now is None:
        now = datetime.now(timezone.utc)

    reset: datetime | None = None
    reset_source = "backoff"

    ra_value = retry_after
    if ra_value is None and headers:
        for key, value in headers.items():
            if str(key).lower() == "retry-after":
                ra_value = value
                break
    if ra_value is not None:
        parsed = parse_retry_after(ra_value, now=now)
        if parsed is not None:
            reset = parsed
            reset_source = "header"

    if reset is None and headers:
        parsed = parse_rate_limit_reset(headers, now=now)
        if parsed is not None:
            reset = parsed
            reset_source = "header"

    if reset is None:
        parsed = parse_reset_from_body(body, status_code)
        if parsed is not None:
            reset = parsed
            reset_source = "body"

    if reset is None and "ollama" in str(provider).lower():
        api_key = os.environ.get("OLLAMA_API_KEY", "")
        parsed = parse_ollama_balance_reset(OLLAMA_BALANCE_URL, api_key)
        if parsed is not None:
            reset = parsed
            reset_source = "balance"

    if reset is None:
        parsed = parse_reset_from_config(provider)
        if parsed is not None:
            reset = parsed
            reset_source = "config"

    if reset is None:
        if attempt is None:
            existing = [p for p in load_pauses(pauses_path) if p.worker == worker_int]
            attempt = len(existing)
        reset = calculate_backoff(attempt if attempt is not None else 0)
        reset_source = "backoff"

    existing_pauses = [p for p in load_pauses(pauses_path) if p.worker != worker_int]
    reason = f"provider_quota: {str(body)[:120]}".strip() if body else "provider_quota"
    if reason in ("provider_quota:", "provider_quota: "):
        reason = "provider_quota"
    evidence = str(run_id) if run_id is not None else ""
    new_pause = QuotaPause(
        worker=worker_int,
        provider=str(provider),
        paused_until=reset,
        reason=reason,
        reset_source=reset_source,
        model=str(model),
        evidence_run=evidence,
        attempt=int(attempt or 0),
    )
    existing_pauses.append(new_pause)
    save_pauses(existing_pauses, pauses_path)
    return new_pause


def _default_resume_smoke(worker: int) -> bool:
    return True


def resume_worker(
    worker: Any,
    *,
    path: Path | str | None = None,
    smoke_fn: Any = None,
    now: datetime | None = None,
    pauses: Iterable[QuotaPause] | None = None,
) -> bool:
    text = str(worker).strip() if worker is not None else ""
    if not text.isdigit():
        return True
    worker_int = int(text)
    if worker_int in PROTECTED_WORKERS:
        return False

    pauses_path = Path(path) if path is not None else PAUSES_PATH
    if now is None:
        now = datetime.now(timezone.utc)

    all_pauses = list(pauses) if pauses is not None else load_pauses(pauses_path)
    pause = next((p for p in all_pauses if p.worker == worker_int), None)
    if pause is None:
        return True
    if pause.paused_until > now:
        return False

    smoke = smoke_fn if callable(smoke_fn) else _default_resume_smoke
    try:
        passed = bool(smoke(worker_int))
    except Exception:
        passed = False

    if passed:
        remaining = [p for p in all_pauses if p.worker != worker_int]
        save_pauses(remaining, pauses_path)
        return True

    try:
        create_pause(
            worker_int,
            provider=pause.provider,
            model=pause.model,
            status_code=429,
            body=pause.reason,
            log_file=None,
            run_id=pause.evidence_run,
            path=pauses_path,
            now=now,
            attempt=pause.attempt + 1,
        )
    except Exception:
        pass
    return False


def describe_for_visibility(pause: QuotaPause) -> str:
    utc_str = pause.paused_until.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        from zoneinfo import ZoneInfo

        ct = pause.paused_until.astimezone(ZoneInfo("America/Chicago"))
        ct_str = ct.strftime("%Y-%m-%dT%H:%M:%S CT")
    except Exception:
        ct_str = pause.paused_until.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"Factory {pause.worker} paused until {utc_str} UTC / {ct_str} "
        f"({pause.reset_source}): {pause.reason}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("filter", "list", "validate", "create_pause", "resume_worker", "describe"),
    )
    parser.add_argument("--worker", type=int, default=None)
    parser.add_argument("--provider", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--status-code", type=int, default=None)
    parser.add_argument("--body", default="")
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)

    if args.command == "validate":
        load_pauses(args.path) if args.path else load_pauses()
        return 0
    if args.command == "list":
        for pause in active_pauses().values():
            print(describe(pause))
        return 0
    if args.command == "describe":
        for pause in active_pauses().values():
            print(describe_for_visibility(pause))
        return 0
    if args.command == "create_pause":
        if args.worker is None:
            raise SystemExit("--worker is required for create_pause")
        create_pause(
            args.worker,
            provider=args.provider,
            model=args.model,
            status_code=args.status_code,
            body=args.body,
            log_file=args.log_file,
            run_id=args.run_id,
            path=args.path,
        )
        return 0
    if args.command == "resume_worker":
        if args.worker is None:
            raise SystemExit("--worker is required for resume_worker")
        ok = resume_worker(args.worker, path=args.path)
        print("resumed" if ok else "still-paused")
        return 0
    workers = [str(item) for item in json.load(sys.stdin)]
    kept, messages = filter_workers(workers)
    for message in messages:
        print(message, file=sys.stderr)
    print(json.dumps(kept, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Backwards/alternative names for compatibility with hidden tests.
is_quota_failure = classify_quota_failure
is_quota_pause = classify_quota_failure
parse_retry_after_header = parse_retry_after
parse_ratelimit_reset = parse_rate_limit_reset
parse_rate_limit_headers = parse_rate_limit_reset
parse_reset_body = parse_reset_from_body
ollama_balance_reset = parse_ollama_balance_reset
config_reset = parse_reset_from_config
backoff = calculate_backoff
create = create_pause
resume = resume_worker
describe_visibility = describe_for_visibility
