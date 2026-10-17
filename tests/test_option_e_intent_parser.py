"""Reviewed intent must reject misspelled decisions instead of dropping them."""

import pytest

from scripts.plan_option_e_conversion import parse_intent


@pytest.mark.parametrize(
    "section",
    [
        None,
        "lists",
        "acknowledged_discrepancies",
        "prerequisites",
        "exclusions",
        "frontier_repairs",
    ],
)
def test_unknown_intent_keys_are_rejected(section: str | None) -> None:
    """Every intent object boundary rejects an unrecognized key."""
    payload: dict[str, object] = {"source_fingerprint": "reviewed"}
    if section is None:
        payload["exclusion"] = []
    elif section == "acknowledged_discrepancies":
        payload["lists"] = [
            {
                "list_id": 5,
                "mode": "loose",
                "acknowledged_discrepancies": [{"issue_id": 10, "kind": "list_only", "typo": True}],
            }
        ]
    else:
        payload[section] = [{"typo": True}]
    with pytest.raises(ValueError, match="Unknown .* keys"):
        parse_intent(payload)


def test_supported_intent_keys_round_trip() -> None:
    """Strict key validation accepts every documented decision field."""
    intent = parse_intent(
        {
            "source_fingerprint": "reviewed",
            "schema_version": 1,
            "lists": [
                {
                    "list_id": 5,
                    "mode": "loose",
                    "gates": [[10, "hold"]],
                    "skipped_issue_ids": [11],
                    "acknowledged_discrepancies": [{"issue_id": 12, "kind": "plan_only"}],
                }
            ],
            "prerequisites": [
                {
                    "dependency_id": 7,
                    "action": "convert",
                    "classification": "A",
                    "provenance": "reviewed",
                }
            ],
            "exclusions": [
                {
                    "provider": "comicvine",
                    "external_volume_id": "123",
                    "thread_id": None,
                    "issue_id": None,
                    "resolved_issue_ids": [12],
                }
            ],
            "frontier_repairs": [{"thread_id": 1, "derived_issue_id": 10}],
        }
    )
    assert intent.lists[0].gates == ((10, "hold"),)
    assert intent.exclusions[0].resolved_issue_ids == (12,)
    assert intent.frontier_repairs[0].derived_issue_id == 10
