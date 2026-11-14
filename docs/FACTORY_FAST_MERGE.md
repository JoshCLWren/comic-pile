# Factory-only immediate fast merge

## Contract

**Factory-only means merge immediately without waiting for CI or semantic review.** This is the owner-authorized exception to the ordinary factory review / `factory:ready` merge drain. When an eligible PR appears or becomes unowned, the dedicated **Factory-only Fast Merge** workflow attempts the squash merge at once. **Do not wait on CI, poll check runs, run semantic review, or route eligible work through the normal merge queue.**

This exception applies to factory infrastructure only. It does not waive the path allowlist, trusted author, active-ownership/hold restrictions, head-SHA pin, or GitHub's enforcement of branch permissions. The controller **attempts** the merge immediately; GitHub must permit it. If the repository's branch rules still require `CI Summary` from the chosen credential, GitHub rejects the attempt. That is a configuration/credential problem, not a reason to resume an endless CI watch. Do not forge check results or globally remove CI protection for product PRs.

## Implementation and authorization

- [`.github/workflows/factory-fast-merge.yml`](../.github/workflows/factory-fast-merge.yml): runs from trusted `main` on PR open/reopen, synchronize, ready-for-review, or label updates, manual dispatch, and a five-minute recovery scan. **No CI completion dependency.**
- [`.github/scripts/factory-fast-merge.py`](../.github/scripts/factory-fast-merge.py): reads each candidate's current metadata/files and immediately calls GitHub's merge API with `sha=<current head>` and `merge_method=squash`. **No check-run, CI-run, or review lookup.**
- [`.github/factory-fast-merge.json`](../.github/factory-fast-merge.json): owner on/off switch, currently `{"enabled": true}`. Missing/malformed/false disables.
- [`tests/test_factory_fast_merge.py`](../tests/test_factory_fast_merge.py): eligibility, protected paths, exact-head merge call, absence of CI gating, and error reporting.
- The workflow uses the existing `PR_REBASE_TOKEN` secret if available, with the built-in `GITHUB_TOKEN` as fallback. **The selected token must have permission to bypass the required `CI Summary` rule** for the eligible PR, otherwise immediate merges are blocked by GitHub. Configure a narrowly authorized ruleset bypass actor/credential if needed; do not relax required CI for unrelated/product PRs. A PAT being an owner PAT does not on its own prove bypass authority.

## Operator / agent procedure

1. Complete the factory-only change and local targeted checks before pushing. Create a **non-draft**, same-repository PR against `main`. Keep product changes separate.
2. Ensure labels include `factory` and `factory:unowned`; release any actual worker lease legitimately. Do not strip active owner/hold labels merely to force a merge.
3. The PR open/label event automatically runs the **Factory-only Fast Merge** action. If a one-shot targeted recovery is needed, use:
   ```bash
   gh workflow run factory-fast-merge.yml --ref main -f pr=1234
   ```
   Replace `1234` with the PR number. A run is an immediate merge **attempt**, not a delayed approval or auto-merge request.
4. Read the action's JSON result: `merged` contains confirmed PR numbers, and `skipped` contains concrete refusal reasons. A green *workflow* with an empty `merged` list is **not** proof of a merge.
5. If GitHub accepts the merge, verify the PR is actually merged and the usual production deployment and linked-issue reconciliation are triggered. If GitHub rejects it for branch protection, fix the scoped permission/bypass configuration; don't pretend waiting for CI is the fast lane.

**No CI polling loop.** A PR that the fast gate has rejected is not improved by checking the same status repeatedly. Perform at most one targeted evaluation on known changes and respond to the reported reason.

## Eligibility, enforced by trusted main

The gate requires **all** of the following:

- Switch explicitly enabled, PR open, non-draft, mergeable with a valid exact head SHA, and targeting this repository's `main`.
- Same-repository head, not a fork; trusted author association (`OWNER`, `MEMBER`, `COLLABORATOR`) or `github-actions[bot]`. Dependabot and Renovate are excluded.
- Both `factory` and `factory:unowned` labels. No `factory:local` or `factory:<number>` active owner; no `factory:blocked`, `needs-human`, `do-not-merge`, or `security-review` hold.
- Every changed path matches the **explicit factory-only allowlist** in the Python controller, including both sides of renames. Complete file enumeration required; unknown or mixed product paths fail closed.
- If one of the three roster artifacts is modified, all three must be in the same PR: `.github/free-model-factories.tsv`, `.github/factory-expected-workers.json`, `.github/factory-roster-snapshot.json`.
- GitHub accepts the SHA-pinned merge with the selected token. A branch-rule rejection becomes a visible `skipped` reason, never a synthetic approval/check.

**No CI / review eligibility requirement exists in this lane.** `factory:changes-requested` status does not by itself prevent this authorized factory-only merge. The controller never executes PR-head code with a write credential, only trusted `main`.

The allowlist covers selected factory scripts, workflows, factory tests, factory docs/skills and atomic roster changes. It does **not** include arbitrary `.github/**` changes. The fast-lane control files themselves are excluded to prevent self-authorized policy edits: `.github/factory-fast-merge.json`, `.github/workflows/factory-fast-merge.yml`, `.github/scripts/factory-fast-merge.py`, and `tests/test_factory_fast_merge.py`. Changes to those controls follow the normal protected path; subsequent ordinary factory-only PRs can demonstrate the newly installed lane.

## After merge and troubleshooting

A successful bot merge with `GITHUB_TOKEN` does not emit a normal push event. The trusted merge script therefore dispatches Deploy Production in its `finally` block after any successful merge, even if a later PR fails. The workflow also runs the post-merge issue-closure reconciliation sweep.

| Result | Next action |
| --- | --- |
| `enabled: false` | Fix the owner switch via the protected normal path |
| Missing labels, active lease or hold | Repair genuine ownership/status, do not remove safety controls as a shortcut |
| Outside allowlist, fork, draft, or unmergeable | Make an eligible factory-only PR or use the ordinary path |
| `GitHub rejected immediate merge` with a required-CI message | Fix the authorized bypass actor/branch rule configuration; **do not convert this into CI waiting** |
| `merged` contains the PR | Verify its merged state and production/closure separately |
| Workflow green but `merged: []` | Read the skip reason. Success only means the evaluation ran |

See [`AUTONOMOUS_FACTORY_POLICY.md`](AUTONOMOUS_FACTORY_POLICY.md) for the normal gated merge path and other factory safety contracts.
