# Issue #2875 implementation status

Coordination issue: "Use the existing Factory to implement the first Latticery extraction slice."

## What this branch adds (ComicPile side)

- `app/api/delivery.py` — authenticated delivery-ledger HTTP API mounted under `/api/v1/delivery`. <!-- docs-path-check: ignore -->
- `app/main.py` — registers the delivery router on the versioned surface only.
- `app/schemas/delivery.py` — `DeliveryFilePayload` plus `files` / `commit_message` on `CrossRepoDeliveryRequest`.
- `app/services/delivery.py` — `list_delivery_records` and `_apply_delivery_files` so a delivery commits real file content before opening the target PR (bootstrap fix: prior behavior opened an empty branch/PR).
- `tests/test_delivery.py` — regression coverage for file payloads and content commit behavior.

## What is already true from prior issues

- #2874 is closed; the cross-repository delivery bridge exists (`DeliveryService`, ledger, credential boundary).
- #2870 is closed; pure dependency/executable policy was staged in ComicPile (`latticery_extraction/`, since retired under #4750 as an abandoned handoff; the retained reference is [.github/scripts/factory_work_policy_latticery_ref.py](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory_work_policy_latticery_ref.py)).
- Execution workers release leases while waiting on external review/CI (controller claim-release markers).

## What is still required to close #2875

These acceptance criteria are **not** satisfied by merging this ComicPile PR alone:

1. Implementation content lands on a branch in `JoshCLWren/Latticery`.
2. A Latticery PR is opened and linked durably from issue #2875.
3. Latticery tests pass on that PR.
4. No duplicate implementation (delivery must not fork divergent copies).

Actual delivery to Latticery requires `LATTICERY_TOKEN` with repository scope (fail-closed without it). The `github-actions` token used for ComicPile coordination does not have Latticery push permission.

## Deliberate non-goals

- Do not switch ComicPile production Factory controller behavior to consume Latticery yet (#2870 boundary).
- Do not auto-merge a Latticery PR solely to prove the mechanism while cross-repo merge gates are incomplete.
