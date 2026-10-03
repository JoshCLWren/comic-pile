"""Unit coverage for the shared factory eligibility semantics.

These tests pin the canonical rules in ``scripts/factory_eligibility.py``
that both work-selection paths (``scripts/next_task.py`` and
``.github/scripts/factory_work_policy.py``) must honor without drift.
"""

import scripts.factory_eligibility as eligibility
import scripts.next_task as next_task


def _policy():
    """Load the fixed-model controller policy module."""
    import importlib.util
    import sys
    from pathlib import Path

    scripts_dir = Path("scripts").resolve()
    controller_dir = Path(".github/scripts").resolve()
    for entry in (str(scripts_dir), str(controller_dir)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location(
        "factory_work_policy_under_test",
        controller_dir / "factory_work_policy.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manual_only_standalone_directive_excludes() -> None:
    """A standalone directive line disallows autonomous execution."""
    assert eligibility.is_manual_only("<!-- factory-execution:manual-only -->\nGate.")
    assert eligibility.is_manual_only("Gate.\n   <!-- factory-execution:manual-only -->   \n")
    assert eligibility.is_manual_only("<!--factory-execution:manual-only-->")


def test_manual_only_prose_discussion_stays_eligible() -> None:
    """Merely discussing the marker in prose must not trigger exclusion."""
    assert not eligibility.is_manual_only(
        "The manual-only marker is reserved for human gates."
    )
    assert not eligibility.is_manual_only(
        "The issue's <!-- factory-execution:manual-only --> marker reserves this."
    )
    assert not eligibility.is_manual_only(
        "Human review boundary plus <!-- factory-execution:manual-only --> hold."
    )
    assert not eligibility.is_manual_only(None)
    assert not eligibility.is_manual_only("")


def test_manual_only_quoted_in_code_stays_eligible() -> None:
    """Quoting the marker in inline code or fenced blocks never excludes."""
    assert not eligibility.is_manual_only(
        "The `<!-- factory-execution:manual-only -->` marker is human-only."
    )
    assert not eligibility.is_manual_only(
        "```\n<!-- factory-execution:manual-only -->\n```\nOrdinary work."
    )
    assert not eligibility.is_manual_only(
        "```markdown\n<!-- factory-execution:manual-only -->\n```"
    )


def test_inline_depends_on_single_and_cluster() -> None:
    """Inline declarations capture the leading reference cluster."""
    assert eligibility.parse_declared_dependencies("Depends on #2126") == {2126}
    assert eligibility.parse_declared_dependencies("depends on #42") == {42}
    assert eligibility.parse_declared_dependencies(
        "Depends on #2126, #2127, and #2128 being merged"
    ) == {2126, 2127, 2128}
    assert eligibility.parse_declared_dependencies("Depends on #2126 + #2127") == {
        2126,
        2127,
    }


def test_inline_depends_on_ignores_casual_mentions() -> None:
    """Casual references without a declaration never block."""
    assert eligibility.parse_declared_dependencies("See also #100 and #200.") == set()
    assert eligibility.parse_declared_dependencies(
        "Depends on #10 and #11 being merged; see also #12 for reads."
    ) == {10, 11}
    # The #2553 shape: historical references with no declaration.
    assert eligibility.parse_declared_dependencies(
        "#2551 is complete. Frozen by #2366. #2363 is closed."
    ) == set()


def test_markdown_wrapped_references_still_declare() -> None:
    """Backticks, bold, and links around a reference never hide it."""
    assert eligibility.parse_declared_dependencies("Depends on `#19` being merged.") == {19}
    assert eligibility.parse_declared_dependencies("Depends on **#19** first.") == {19}
    assert eligibility.parse_declared_dependencies(
        "Depends on [#19](https://example.test/issues/19) first."
    ) == {19}


def test_heading_list_declares_dependencies() -> None:
    """A dependency heading followed by a reference list blocks intake."""
    assert eligibility.parse_declared_dependencies("## Depends on\n\n- #2721") == {2721}
    assert eligibility.parse_declared_dependencies(
        "## Dependencies\n\n- #19\n- #21\n"
    ) == {19, 21}
    assert eligibility.parse_declared_dependencies(
        "Blocked by:\n\n1. #7\n2. #8\n"
    ) == {7, 8}
    assert eligibility.parse_declared_dependencies(
        "## Prerequisites\n\n* #3\n"
    ) == {3}


def test_heading_list_stops_at_prose() -> None:
    """List collection ends where the list ends."""
    assert eligibility.parse_declared_dependencies(
        "## Dependencies\n\n- #19\n\nUnrelated #20 mention."
    ) == {19}


def test_heading_without_list_declares_nothing() -> None:
    """A bare heading with no reference items is not a declaration."""
    assert eligibility.parse_declared_dependencies("## Dependencies\n\nNone.") == set()


def test_owner_helpers() -> None:
    """Ownership helpers agree on active, unowned, and absent leases."""
    assert eligibility.owner_of({"factory:58"}) == "factory:58"
    assert eligibility.owner_of({"factory:local"}) == "factory:local"
    assert eligibility.owner_of({"factory:unowned"}) == "factory:unowned"
    assert eligibility.owner_of(set()) is None
    assert eligibility.has_active_factory_owner({"factory:58", "factory:building"})
    assert eligibility.has_active_factory_owner({"factory:local"})
    assert not eligibility.has_active_factory_owner({"factory:unowned"})
    assert not eligibility.has_active_factory_owner(set())
    assert eligibility.is_factory_unowned({"factory:unowned"})
    assert eligibility.is_factory_unowned(set())
    assert not eligibility.is_factory_unowned({"factory:7"})


def test_machine_marker_trust_requires_workflow_provenance() -> None:
    """Only workflow-posted comments prove machine-marker provenance."""
    app_comment = {
        "author_association": "CONTRIBUTOR",
        "performed_via_github_app": {"slug": "github-actions"},
    }
    assert eligibility.machine_marker_is_trusted(app_comment)
    assert not eligibility.machine_marker_is_trusted({"author_association": "OWNER"})
    assert not eligibility.machine_marker_is_trusted({"author_association": "MEMBER"})
    assert not eligibility.machine_marker_is_trusted({"author_association": "COLLABORATOR"})
    assert not eligibility.machine_marker_is_trusted({"author_association": "CONTRIBUTOR"})
    assert not eligibility.machine_marker_is_trusted(
        {
            "author_association": "CONTRIBUTOR",
            "performed_via_github_app": {"slug": "other-app"},
        }
    )
    assert not eligibility.machine_marker_is_trusted({})


def test_explain_marks_fully_eligible_issue() -> None:
    """An unowned, unblocked, dependency-free issue explains as eligible."""
    verdict = eligibility.explain_issue_eligibility(
        number=2553,
        state="OPEN",
        labels={"bug", "ralph-task", "ralph-status:pending", "factory:unowned"},
        body="Frozen contract. #2551 is complete.",
        open_numbers={2553},
    )

    assert verdict.eligible
    assert verdict.reasons == ("eligible: no static exclusion applies",)


def _verdict(
    labels: set[str],
    body: str = "",
    state: str = "OPEN",
    number: int = 10,
    open_numbers: set[int] | None = None,
    suppressing_issue_numbers: set[int] | None = None,
    non_executable_numbers: set[int] | None = None,
    no_diff_attempts: int = 0,
    no_diff_limit: int = 3,
    require_ralph_labels: bool = False,
) -> eligibility.EligibilityVerdict:
    """Build a static verdict for one fixture with shared defaults."""
    return eligibility.explain_issue_eligibility(
        number=number,
        state=state,
        labels=labels,
        body=body,
        open_numbers={number} if open_numbers is None else open_numbers,
        suppressing_issue_numbers=suppressing_issue_numbers,
        non_executable_numbers=non_executable_numbers,
        no_diff_attempts=no_diff_attempts,
        no_diff_limit=no_diff_limit,
        require_ralph_labels=require_ralph_labels,
    )


def test_explain_names_each_static_exclusion() -> None:
    """Every static exclusion surfaces as a human-readable reason."""
    assert not _verdict({"epic"}).eligible
    manual = _verdict(set(), body="<!-- factory-execution:manual-only -->\nGate.")
    assert not manual.eligible
    assert any("manual-only" in reason for reason in manual.reasons)
    owned = _verdict({"factory:58"})
    assert not owned.eligible
    assert any("factory:58" in reason for reason in owned.reasons)
    assert not _verdict({"ralph-status:blocked"}).eligible
    assert not _verdict({"ralph-status:done"}).eligible
    assert not _verdict(set(), state="CLOSED").eligible
    suppressed = _verdict(set(), suppressing_issue_numbers={10})
    assert not suppressed.eligible
    assert any("canonical PR" in reason for reason in suppressed.reasons)
    exhausted = _verdict(set(), no_diff_attempts=3, no_diff_limit=3)
    assert not exhausted.eligible
    assert any("retry budget" in reason for reason in exhausted.reasons)


def test_explain_dependency_reason_names_open_prerequisites() -> None:
    """Unresolved heading-declared dependencies name their open targets."""
    verdict = eligibility.explain_issue_eligibility(
        number=2722,
        state="OPEN",
        labels={"factory:unowned"},
        body="## Depends on\n\n- #2721\n",
        open_numbers={2721, 2722},
    )

    assert not verdict.eligible
    assert any("#2721" in reason for reason in verdict.reasons)


def test_explain_ralph_labels_are_opt_in() -> None:
    """Ralph-selector metadata gates only Ralph selection, never the queue."""
    labels = {"factory:unowned"}
    assert eligibility.explain_issue_eligibility(
        number=1, state="OPEN", labels=labels, body="", open_numbers={1}
    ).eligible
    ralph = eligibility.explain_issue_eligibility(
        number=1,
        state="OPEN",
        labels=labels,
        body="",
        open_numbers={1},
        require_ralph_labels=True,
    )
    assert not ralph.eligible
    assert any("Ralph-selector metadata" in reason for reason in ralph.reasons)


def test_selectors_agree_with_shared_semantics() -> None:
    """Both selectors delegate to the shared module without drift."""
    policy = _policy()
    assert policy.MANUAL_ONLY_MARKER == eligibility.MANUAL_ONLY_MARKER
    assert set(policy.BLOCKED_LABELS) == set(eligibility.BLOCKED_LABELS)
    assert policy.OWNER_RE.pattern == eligibility.FACTORY_OWNER_RE.pattern
    assert policy.owner_of({"factory:58"}) == eligibility.owner_of({"factory:58"})
    assert policy.item_is_unowned({"factory:unowned"}) == eligibility.is_factory_unowned(
        {"factory:unowned"}
    )
    bodies = [
        "<!-- factory-execution:manual-only -->\nGate.",
        "The `<!-- factory-execution:manual-only -->` marker is discussed.",
        "Plain prose about manual-only gates.",
        "Depends on #10 and #11.",
        "## Dependencies\n\n- #19\n",
    ]
    for body in bodies:
        assert policy.is_manual_only(body) == eligibility.is_manual_only(body)
        assert policy.is_acceptance_parent(body) == eligibility.is_acceptance_parent(body)
        assert policy.parse_declared_dependencies(body) == (
            eligibility.parse_declared_dependencies(body)
        )
        assert next_task._is_manual_only({"body": body, "number": 1, "title": "t", "labels": [], "url": ""}) == eligibility.is_manual_only(body)
        assert next_task._dependency_numbers(body) == (
            eligibility.parse_declared_dependencies(body)
        )
