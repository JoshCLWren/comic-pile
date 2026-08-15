#!/usr/bin/env python3
"""Classify one completed fixed-model factory run from its Actions job log."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unittest
from dataclasses import asdict, dataclass
from pathlib import Path

LOCK_RE = re.compile(
    r"Factory (?P<worker>\d+) locked: source=(?P<source>\S+) model=(?P<model>\S+) "
    r"runtime=(?P<runtime>\S+) minute=:(?P<minute>\d+) scheduler=(?P<scheduler>\S+) "
    r"configured=(?P<configured>true|false)",
    re.IGNORECASE,
)
TARGET_RE = re.compile(r"checked out (?P<kind>issue|pr) #(?P<number>\d+) on ")
RATE_LIMIT_RE = re.compile(r"429|too many requests|rate.?limit|quota|throttl|capacity", re.I)
MODEL_MISSING_RE = re.compile(
    r"pinned .*model is not currently exposed|unknown model|model .*not found|model .*does not exist",
    re.I,
)
TIMEOUT_RE = re.compile(r"timed? out|timeout|exit status 124|process completed with exit code 124", re.I)
CANCEL_RE = re.compile(r"operation was canceled|operation was cancelled|cancellation requested|job was canceled|job was cancelled", re.I)
PROCESS_FAILURE_RE = re.compile(r"process completed with exit code [1-9][0-9]*|command failed with exit code [1-9][0-9]*", re.I)
PROVIDER_RE = re.compile(
    r"provider error|service unavailable|bad gateway|gateway timeout|502|503|504|"
    r"econnreset|connection reset|model probe failed|failed the opencode compatibility probe",
    re.I,
)

PRODUCTIVE_SIGNALS = (
    "opened/updated PR #",
    "pushed repairs to PR #",
    "all exact-head gates passed for PR #",
)


@dataclass(frozen=True)
class Result:
    """
    Represents the classification result of a model run.
    """

    worker: str = ""
    source: str = ""
    model: str = ""
    runtime_model: str = ""
    minute: str = ""
    configured: bool = False
    exact_model_proven: bool = False
    selected_kind: str = ""
    selected_number: str = ""
    persisted_work: bool = False
    outcome: str = "NOT YET PROVEN"
    detail: str = "factory job did not expose enough runtime evidence"


def classify(log: str) -> Result:
    lock = LOCK_RE.search(log)
    if not lock:
        return Result()

    values = lock.groupdict()
    configured = values["configured"].lower() == "true"
    exact_proven = "FIXED_MODEL_OPENCODE_OK" in log
    target_matches = list(TARGET_RE.finditer(log))
    target = target_matches[-1].groupdict() if target_matches else {"kind": "", "number": ""}
    persisted = any(signal in log for signal in PRODUCTIVE_SIGNALS)

    common = dict(
        worker=values["worker"],
        source=values["source"],
        model=values["model"],
        runtime_model=values["runtime"],
        minute=values["minute"],
        configured=configured,
        exact_model_proven=exact_proven,
        selected_kind=target["kind"],
        selected_number=target["number"],
        persisted_work=persisted,
    )

    if not configured:
        return Result(**common, outcome="NOT YET PROVEN", detail="lane was not configured, so the pinned model was never invoked")

    if MODEL_MISSING_RE.search(log):
        return Result(**common, outcome="MODEL MISSING", detail="the configured provider did not expose the pinned model")

    # Useful persistence wins even if a later cleanup/provider call failed. The
    # run did useful work with the exact model, which is the fleet fact we care about.
    if persisted and exact_proven:
        return Result(**common, outcome="HEALTHY / PRODUCTIVE", detail="exact OpenCode model proof succeeded and useful work was persisted")

    if RATE_LIMIT_RE.search(log):
        return Result(**common, outcome="RATE LIMITED", detail="runtime evidence contains a provider rate-limit or capacity response")

    if TIMEOUT_RE.search(log) or CANCEL_RE.search(log):
        return Result(**common, outcome="TIMEOUT", detail="the pinned-model run was cancelled or exceeded its runtime lease")

    if exact_proven:
        if PROVIDER_RE.search(log) or PROCESS_FAILURE_RE.search(log):
            return Result(**common, outcome="PROVIDER FAILURE", detail="the model proved itself, then the worker/provider runtime failed before useful persistence")
        return Result(**common, outcome="HEALTHY / IDLE", detail="exact OpenCode model proof succeeded but no useful work was persisted")

    # A smoke invocation reached OpenCode but did not produce the proof token.
    if "ComicPile fixed-model smoke" in log or "Smoke exact pinned model through OpenCode" in log:
        return Result(**common, outcome="PROVIDER FAILURE", detail="the exact OpenCode model invocation ran but did not return the proof token")

    # OmniRoute can prove provider/model exposure before OpenCode is reached. Keep
    # model-exposure failures above distinct, while setup failures remain unproven.
    if values["source"] == "omniroute-opencode":
        return Result(**common, outcome="NOT YET PROVEN", detail="OmniRoute setup ended before exact OpenCode model proof")

    return Result(**common, outcome="NOT YET PROVEN", detail="execution ended before exact OpenCode model proof")


class ClassifierTests(unittest.TestCase):
    BASE = "Factory 32 locked: source=omniroute-opencode model=oc/big-pickle runtime=omniroute/oc/big-pickle minute=:15 scheduler=slot-15 configured=true\n"

    """
    Test case for productive model runs.
    """

        result = classify(self.BASE + "FIXED_MODEL_OPENCODE_OK\n[factory:32] checked out issue #928 on x\nopened/updated PR #1220 for issue #928\n")
        self.assertEqual(result.outcome, "HEALTHY / PRODUCTIVE")
        self.assertTrue(result.exact_model_proven)
        self.assertTrue(result.persisted_work)
        self.assertEqual((result.selected_kind, result.selected_number), ("issue", "928"))

    def test_idle(self) -> None:
        self.assertEqual(classify(self.BASE + "FIXED_MODEL_OPENCODE_OK\nno selectable ordinary target\n").outcome, "HEALTHY / IDLE")

    def test_rate_limited(self) -> None:
        self.assertEqual(classify(self.BASE + "ComicPile fixed-model smoke\nError: Too Many Requests 429\n").outcome, "RATE LIMITED")

    def test_model_missing(self) -> None:
        self.assertEqual(classify(self.BASE + "Pinned OmniRoute model is not currently exposed: oc/big-pickle\n").outcome, "MODEL MISSING")

    def test_timeout(self) -> None:
        self.assertEqual(classify(self.BASE + "ComicPile fixed-model smoke\nProcess completed with exit code 124\n").outcome, "TIMEOUT")

    def test_unconfigured(self) -> None:
        log = "Factory 6 locked: source=nvidia model=z-ai/glm-5.2 runtime=nvidia/z-ai/glm-5.2 minute=:00 scheduler=slot-00 configured=false\n"
        self.assertEqual(classify(log).outcome, "NOT YET PROVEN")

    def test_omniroute_setup_failure_is_unproven(self) -> None:
        self.assertEqual(classify(self.BASE + "docker: Error response from daemon\n").outcome, "NOT YET PROVEN")

    def test_failed_exact_smoke_is_provider_failure(self) -> None:
        self.assertEqual(classify(self.BASE + "Smoke exact pinned model through OpenCode\nError: unexpected provider response\n").outcome, "PROVIDER FAILURE")

    def test_post_proof_worker_failure_is_not_healthy(self) -> None:
        result = classify(self.BASE + "FIXED_MODEL_OPENCODE_OK\nRun continuous fixed-model factory session\nProcess completed with exit code 1\n")
        self.assertEqual(result.outcome, "PROVIDER FAILURE")

    def test_post_proof_cancellation_is_timeout(self) -> None:
        result = classify(self.BASE + "FIXED_MODEL_OPENCODE_OK\nThe operation was canceled.\n")
        self.assertEqual(result.outcome, "TIMEOUT")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ClassifierTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if not args.log:
        parser.error("--log is required unless --self-test is used")
    print(json.dumps(asdict(classify(args.log.read_text(encoding="utf-8", errors="replace"))), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
