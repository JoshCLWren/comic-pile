"""Credit-parsing contract for the retained creator-summary projection.

These helpers outlive the retired v1 creator endpoints: the read-without-rating
audit still calls them through ``load_creator_summary_inputs``. Keep their
malformed-input, deduplication and key-selection behavior pinned here now that
the endpoint-level regression file has been removed.
"""

from app.repositories.creator_summary import (
    CREATOR_CREDITS_KEY,
    extract_creator_credit_list,
    extract_creator_credits,
)


def test_extract_creator_credit_list_rejects_unusable_values() -> None:
    """Only a list of credit dictionaries yields credits."""
    assert extract_creator_credit_list(None) == []
    assert extract_creator_credit_list("nope") == []
    assert extract_creator_credit_list({"id": 1}) == []
    assert extract_creator_credit_list([{"name": "No id"}, "not a dict"]) == []
    assert extract_creator_credit_list([{"id": 1, "name": "  "}]) == []
    assert extract_creator_credit_list([{"id": "12", "name": "String id"}])[0].external_id == 12


def test_extract_creator_credit_list_deduplicates_and_sorts_roles() -> None:
    """Distinct (creator, role-set) pairs survive with comma-joined roles split."""
    credits = extract_creator_credit_list(
        [
            {"id": 7, "name": "Seven", "role": "penciler, writer"},
            {"id": 7, "name": "Seven", "role": "penciler,writer"},
            {"id": 7, "name": "Seven"},
            {"id": 7, "name": "Seven", "role": "inker"},
        ]
    )
    assert [(credit.external_id, credit.roles, credit.display_name) for credit in credits] == [
        (7, ("penciler", "writer"), "Seven"),
        (7, (), "Seven"),
        (7, ("inker",), "Seven"),
    ]


def test_extract_creator_credits_reads_the_named_key() -> None:
    """The whole-document reader stays a thin wrapper over the list reader."""
    raw = [{"id": 3, "name": "Three", "role": "writer"}]
    assert extract_creator_credits({CREATOR_CREDITS_KEY: raw}) == extract_creator_credit_list(raw)
    assert extract_creator_credits({"other": raw}) == []
