# Issue #2875 implementation status

Coordination issue: "Use the existing Factory to implement the first Latticery extraction slice."

## What this branch adds (ComicPile side)

- `app/api/delivery.py` — authenticated delivery-ledger HTTP API mounted under `/api/v1/delivery`.
- `app/main.py` — registers the delivery router on the versioned surface only.
- `app/schemas/delivery.py` — `DeliveryFilePayload` plus `files` / `commit_message` on `CrossRepoDeliveryRequest`.
- `app/services/delivery.py` — `list_delivery_records` and `_apply_delivery_files` so a delivery commits real file content before opening the target PR (bootstrap fix: prior behavior opened an empty branch/PR).
- `scripts/deliver_latticery_extraction.py` — executable delivery path that stages adapted files and calls the delivery service.
- `scripts/deliver_latticery_extraction_simple.py` — dry-run/plan printer (no repository mutation).
- `tests/test_delivery.py` — regression coverage for file payloads and content commit behavior.

## What is already true from prior issues

- #2874 is closed; the cross-repository delivery bridge exists (`DeliveryService`, ledger, credential boundary).
- #2870 is closed; pure dependency/executable policy is staged in ComicPile at `latticery_extraction/`.
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
