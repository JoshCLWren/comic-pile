from scripts.audit_legacy_dependencies import classify


def test_source_generated_cbl_order_is_reading_plan_order() -> None:
    classification, reason, review = classify("cbl-order:source:abc:1->2", ())
    assert classification == "reading_plan_order"
    assert "CBL" in reason
    assert review is False


def test_linked_rule_is_not_assumed_safe() -> None:
    classification, _, review = classify("some historical prerequisite", (42,))
    assert classification == "needs_review"
    assert review is True


def test_unnoted_dependency_requires_review() -> None:
    classification, _, review = classify(None, ())
    assert classification == "needs_review"
    assert review is True
