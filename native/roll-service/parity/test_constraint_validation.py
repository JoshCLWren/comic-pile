"""Compare native global cycle validation with the canonical Python oracle."""

import json
import random
import subprocess
from dataclasses import asdict
from pathlib import Path

from app.services.reading_list_cycle_validator import ReadingCycleError, validate_reading_constraints
from app.services.reading_list_evaluator import (
    ReadingIssue, ReadingList, ReadingListEntry, ReadingPrerequisite, ReadingSnapshot,
    ReadingThread, SeriesOverlapDecision,
)

RUNNER = Path(__file__).resolve().parents[1] / "target/debug/examples/constraint_validation"
READER_ID = 937


def oracle(data: dict[str, object]) -> dict[str, object]:
    """Compare complete order or error payload, including cycle origins/provenance."""
    raw = json.loads(json.dumps(data))
    try:
        snapshot = ReadingSnapshot(
            user_id=READER_ID,
            threads=tuple(ReadingThread(**t) for t in raw.get("threads", [])),
            issues=tuple(ReadingIssue(**i) for i in raw.get("issues", [])),
            lists=tuple(ReadingList(
                **{k: v for k, v in row.items() if k not in ("entries", "overlap_decisions")},
                entries=tuple(ReadingListEntry(**e) for e in row.get("entries", [])),
                overlap_decisions=tuple(SeriesOverlapDecision(**d)
                                        for d in row.get("overlap_decisions", [])),
            ) for row in raw.get("lists", [])),
            prerequisites=tuple(ReadingPrerequisite(**p) for p in raw.get("prerequisites", [])),
            excluded_issue_ids=frozenset(raw.get("excluded_issue_ids", [])),
        )
        return {"order": list(validate_reading_constraints(snapshot))}
    except ReadingCycleError as error:
        return json.loads(json.dumps({"kind": "cycle", "message": str(error),
                                      "edges": [asdict(e) for e in error.edges]}))
    except ValueError as error:
        return {"kind": "invalid_snapshot", "message": str(error)}


def compare(cases: list[dict[str, object]]) -> None:
    """Run a bounded offline native process against sanitized scalar snapshots."""
    result = subprocess.run([str(RUNNER)], input="\n".join(json.dumps(c) for c in cases),
                            text=True, capture_output=True, timeout=30, check=True)
    actual = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(actual) == len(cases)
    for index, (case, native) in enumerate(zip(cases, actual, strict=True)):
        assert native == oracle(case), f"case {index}: {case}"


def base() -> dict[str, object]:
    """Four series with interleaved identities and mixed read/unread status."""
    return {
        "threads": [{"thread_id": t, "name": f" Series {t} ",
                     "comicvine_volume_id": f"comicvine:{t}"} for t in range(1, 5)],
        "issues": [{"issue_id": i, "thread_id": (i - 1) % 4 + 1, "position": i,
                    "status": "read" if i % 3 == 0 else "unread"} for i in range(1, 13)],
    }


def test_constraint_matrix() -> None:
    """Seeded cross-list graphs exercise strict/loose, holds, overlaps and exclusions."""
    cases: list[dict[str, object]] = [{}, base()]
    rng = random.Random(4306)
    for _ in range(250):
        case = base()
        lists = []
        for list_id in range(1, rng.randrange(2, 5)):
            order = rng.sample(range(1, 13), rng.randrange(2, 13))
            pairs = rng.sample([(a, b) for a in range(1, 5) for b in range(1, 5) if a != b],
                               rng.randrange(5))
            lists.append({"list_id": list_id, "name": f" List {list_id} ",
                          "mode": rng.choice(["strict", "loose"]),
                          "entries": [{"issue_id": i, "gate": rng.choice(
                              ["none", "none", "hold", "after_previous"]),
                                       "skipped": rng.random() < 0.2} for i in order],
                          "overlap_decisions": [{"continuing_volume_id": f"comicvine:{a}",
                                                 "waiting_volume_id": f"comicvine:{b}"}
                                                for a, b in pairs]})
        case["lists"] = lists
        source, target = rng.sample(range(1, 13), 2)
        case["prerequisites"] = [{"prerequisite_id": 71, "source_issue_id": source,
                                   "target_issue_id": target,
                                   "origin": rng.choice(["reader", "converted"]),
                                   "provenance": ["approved", "historical classification unknown"]}]
        case["excluded_issue_ids"] = [i for i in range(1, 13)
                                       if i != source and rng.random() < 0.3]
        cases.append(case)
    compare(cases)
    assert any("order" in oracle(c) for c in cases)
    assert any(oracle(c).get("kind") == "cycle" for c in cases)


def test_invalid_references_and_contracts() -> None:
    """Missing/foreign references and corrupt enums fail closed, even when skipped."""
    patches = [
        {"threads": [{"thread_id": 1}, {"thread_id": 1}]},
        {"issues": [{"issue_id": 8, "thread_id": 99, "position": 1}]},
        {"excluded_issue_ids": [999]},
        {"lists": [{"list_id": 1, "mode": "unknown"}]},
        {"lists": [{"list_id": 1, "mode": "strict", "entries": [{"issue_id": 1}, {"issue_id": 1}]}]},
        {"lists": [{"list_id": 1, "mode": "loose", "entries": [{"issue_id": 1, "gate": "bad"}]}]},
        {"lists": [{"list_id": 1, "mode": "loose", "entries": [{"issue_id": 999, "skipped": True}]}]},
        {"prerequisites": [{"prerequisite_id": 1, "source_issue_id": 999,
                            "target_issue_id": 1, "origin": "reader"}]},
        {"prerequisites": [{"prerequisite_id": 1, "source_issue_id": 1,
                            "target_issue_id": 2, "origin": "bad"}]},
        {"prerequisites": [{"prerequisite_id": 1, "source_issue_id": 1,
                            "target_issue_id": 2, "origin": "reader"}], "excluded_issue_ids": [1]},
    ]
    cases = [{**base(), **p} for p in patches]
    for a, b in [("", "b"), ("a", "a")]:
        cases.append({**base(), "lists": [{"list_id": 1, "mode": "strict", "overlap_decisions": [
            {"continuing_volume_id": a, "waiting_volume_id": b}]}]})
    compare(cases)


def test_long_lists_and_residual_cycle() -> None:
    """Twenty thousand entries, including a long residual cycle, need no recursion."""
    count = 20000
    case = {"threads": [{"thread_id": 1}],
            "issues": [{"issue_id": i, "thread_id": 1, "position": i}
                       for i in range(1, count + 1)],
            "lists": [{"list_id": 1, "mode": "strict",
                       "entries": [{"issue_id": i} for i in range(1, count + 1)]}]}
    compare([case, {**case, "prerequisites": [{"prerequisite_id": 1,
              "source_issue_id": count, "target_issue_id": count // 2, "origin": "reader",
              "provenance": ["long residual cycle"]}]}])


def test_overlap_exempts_only_implicit_pair_and_skips_only_local_placement() -> None:
    """Approval removes one strict edge; gates, unknown volumes and other lists retain it."""
    case = {"threads": [{"thread_id": 1, "comicvine_volume_id": "a"},
                        {"thread_id": 2, "comicvine_volume_id": "b"}],
            "issues": [{"issue_id": 1, "thread_id": 1, "position": 1, "status": "read"},
                       {"issue_id": 2, "thread_id": 2, "position": 1}],
            "lists": [{"list_id": 1, "mode": "strict", "entries": [
                {"issue_id": 1}, {"issue_id": 2}], "overlap_decisions": [
                {"continuing_volume_id": "b", "waiting_volume_id": "a"}]}],
            "prerequisites": [{"prerequisite_id": 1, "source_issue_id": 2,
                               "target_issue_id": 1, "origin": "reader"}]}
    assert "order" in oracle(case)
    cases = [case]
    for gate in ["hold", "after_previous"]:
        changed = json.loads(json.dumps(case))
        changed["lists"][0]["entries"][1]["gate"] = gate
        assert oracle(changed)["kind"] == "cycle"
        cases.append(changed)
    unknown = json.loads(json.dumps(case))
    unknown["threads"][1].pop("comicvine_volume_id")
    assert oracle(unknown)["kind"] == "cycle"
    cases.append(unknown)
    other = json.loads(json.dumps(case))
    other["lists"].append({"list_id": 2, "mode": "strict", "entries": [
        {"issue_id": 1}, {"issue_id": 2}]})
    assert oracle(other)["kind"] == "cycle"
    cases.append(other)
    skipped = json.loads(json.dumps(other))
    skipped["lists"][1]["entries"][0]["skipped"] = True
    assert "order" in oracle(skipped)
    cases.append(skipped)
    compare(cases)
