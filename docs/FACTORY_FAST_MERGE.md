# Factory-only fast merge

The owner-controlled switch is `.github/factory-fast-merge.json`:

```json
{"enabled": true}
```

Set `enabled` to `false` to turn off both the factory-only CI shortcut and fast merging. Changes to the switch, global CI workflow, merge workflow, merge policy script, and its tests are excluded from fast merging. Those policy changes must pass full CI.

## Eligibility

The trusted policy in `.github/scripts/factory-fast-merge.py` checks that every changed file is on the factory-only allowlist, including both sides of any rename; the PR is a trusted same-repository, non-draft, mergeable head targeting `main`; it has `factory` and `factory:unowned` labels; and no owner, block, or security hold is active.

Forks, mixed factory/product changes, partial or unknown file lists, and changes to the fast-merge policy are excluded. Unknown paths fail closed.

## Fast path

For eligible factory-only PRs, **CI** first runs `factory_fast_preflight` against the policy checked out from trusted `main`, not PR code. If eligible **and the owner switch is enabled**, expensive unrelated product test and build jobs are skipped. The required `CI Summary` succeeds after the preflight. The ordinary CI suite still runs for other PRs and for `main`.

**Factory-only Fast Merge** wakes on PR events, CI completion, and its scheduled fallback. It only uses the trusted `main` implementation, verifies the successful authentic `CI Summary` and CI workflow run at the exact PR SHA, and squashes the eligible head. It does not waive the repository's required `CI Summary` branch rule or semantic-review safety checks on non-factory code.

The merge script dispatches production after a merge even if another PR later fails in the same scan; the workflow runs post-merge issue reconciliation. A failed or unavailable preflight, failing CI, blocked PR, or outdated head cannot merge through this path.

## End-to-end verification

To verify a fast-lane change, confirm that the new PR's preflight prints `eligible: True`, unrelated CI jobs are skipped, `CI Summary` succeeds, and the fast-merge workflow records the exact PR as merged. Check that a policy or product PR still runs all required CI jobs.
