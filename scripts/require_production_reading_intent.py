"""Fail-closed migration signoff, separate from green tests of reviewed sequences.

This command must be part of any claim that Option E preserves reader intent.
A clean migration preview or green current Roll frontier is not an approval.
"""

import argparse
import json
from pathlib import Path

DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / (
    "tests/fixtures/production_reading_expectations_v1.json"
)


def incomplete_intent_reasons(contract: dict[str, object]) -> list[str]:
    """Report unresolved source, coverage and reader-approval evidence.

    Args:
        contract: Separately reviewed expected-order manifest, not evaluator output.

    Returns:
        Human-readable reasons that prevent a full migration signoff.
    """
    problems: list[str] = []
    status = contract.get("reader_intent_signoff")
    if status != "approved":
        problems.append("Reader-intent signoff has not been explicitly approved")
    unresolved = contract.get("unresolved_reader_intent")
    if not isinstance(unresolved, dict):
        return [*problems, "Missing unresolved-intent census"]
    for label, value in unresolved.items():
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            problems.append(f"Unresolved reader intent: {label} = {value}")
    reviewed = contract.get("reviewed_source_decisions")
    if not isinstance(reviewed, list) or not reviewed:
        problems.append("No independent reconciliation decision receipts")
    else:
        for index, decision in enumerate(reviewed):
            if not isinstance(decision, dict) or not all(
                decision.get(key) for key in ("source", "discrepancy", "decision", "reviewed_by")
            ):
                problems.append(f"Missing provenance for reader decision #{index + 1}")
    if not contract.get("fixture_git_blob_sha"):
        problems.append("Fixture has no independently pinned reviewed digest")
    return problems


def main() -> int:
    """Emit nonzero exit when a migration would falsely claim semantic parity."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    problems = incomplete_intent_reasons(contract)
    for reason in problems:
        print(f"BLOCKED: {reason}")
    if problems:
        print("Migration semantic parity NOT established. Do not merge as parity-complete.")
        return 1
    print("Reader-intent review receipts and approved migration signoff present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
