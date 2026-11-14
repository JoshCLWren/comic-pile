# Factory-only fast merge

## Purpose and precedence

**Use the Factory-only Fast Merge lane for eligible factory infrastructure PRs, not the ordinary semantic-review / `factory:ready` drain.** This is the repository's owner-enabled exception to the normal factory review gate. The intent is to land self-contained factory repairs promptly without spending worker/model capacity on repeated review or CI polling.

"Fast" means **no semantic review** and **event-driven merging immediately after authentic exact-head CI succeeds**. It does **not** mean "ignore CI" or "merge while CI is red/pending." A request to "fast lane this" should route directly here, rather than through the standard review controller. Do not represent a normal merge, an auto-merge setting, or a loop of GitHub status checks as use of this lane.

The implementation, not prose, is authoritative:

- Trigger and orchestration: [`.github/workflows/factory-fast-merge.yml`](../.github/workflows/factory-fast-merge.yml) (GitHub Actions name **Factory-only Fast Merge**)
- Eligibility, CI verification and SHA-pinned squash: [`.github/scripts/factory-fast-merge.py`](../.github/scripts/factory-fast-merge.py)
- Owner switch: [`.github/factory-fast-merge.json`](../.github/factory-fast-merge.json)
- Contract tests: [`tests/test_factory_fast_merge.py`](../tests/test_factory_fast_merge.py)
- Normal delivery policy: [`AUTONOMOUS_FACTORY_POLICY.md`](AUTONOMOUS_FACTORY_POLICY.md)

## Operator procedure: use the fast lane, once

1. **Make the PR factory-only.** Open a non-draft PR against `main` from a branch in this repository. Finish the actual fix and its relevant local checks before pushing. Do not mix product files into the PR to make a larger change ride along.
2. **Release its lease normally.** It must have both `factory` and `factory:unowned` labels, with no active `factory:local` or numbered `factory:<n>` owner, hold, or disqualifying label. Never remove a genuinely active lease just to get a merge.
3. **Let the dedicated workflow run.** It is automatically triggered by PR open/reopen, ready-for-review, new commits, label changes, and successful completion of the `CI` workflow. It also scans on a five-minute schedule for missed events. A new `factory:ready` label, semantic review, or human reapproval is **not** required.
4. **For an urgent eligible PR, dispatch one targeted evaluation** instead of waiting for the fallback scan:
   ```bash
   gh workflow run factory-fast-merge.yml --ref main -f pr=1234
   ```
   Replace `1234` with the actual PR number. This queues the lane; it cannot manufacture a successful CI result. In the GitHub UI, use **Actions → Factory-only Fast Merge → Run workflow**, supplying the optional PR number. Omitting the PR number scans open PRs.
5. **Read the outcome, then act on evidence.** The trusted script outputs JSON containing `enabled`, `merged` PR numbers, and `skipped` reasons. If merged, verify the PR's merged state and, when the objective requires it, the deployment/production result. If skipped, repair the named defect or allow the existing completion trigger to pick it up.

**Do not loop checking CI every few seconds or repeatedly redispatch the fast workflow.** If CI is pending, the `workflow_run` completion event is the next opportunity. If CI failed, fix the failure and push a new head. If the head changed, its old checks no longer count. One useful status inspection is better than a polling marathon. Continue other executable work rather than burning the session on unchanged check state.

## Exact eligibility contract

The trusted controller requires all of the following:

- The switch contains the JSON boolean `{"enabled": true}`. Missing, malformed, or other values disable the lane. On the inspected version of `main`, it is enabled.
- PR is **open**, **non-draft**, **mergeable**, targets this repository's `main`, and has a valid 40-character head SHA.
- Head is **same-repository**, not a fork. The author is an `OWNER`, `MEMBER`, or `COLLABORATOR`, or `github-actions[bot]`; Dependabot and Renovate are excluded.
- Labels include `factory` and `factory:unowned`. No `factory:local` or `factory:<number>` ownership label and no `factory:blocked`, `needs-human`, `do-not-merge`, or `security-review` hold.
- **Every changed file** is on the strict factory allowlist in the controller. A rename must have both old and new paths allowed; unknown or mixed product paths fail closed. File pagination must be complete, and PRs at GitHub's 3,000-file listing boundary are excluded.
- If any of the three roster artifacts is touched, **all three** must appear together: `.github/free-model-factories.tsv`, `.github/factory-expected-workers.json`, and `.github/factory-roster-snapshot.json`.
- The **latest** authentic GitHub Actions `CI Summary` check run for the **exact current head** has completed successfully, and a genuine successful `CI` workflow run exists for that same SHA (`pull_request` or `workflow_dispatch`). A stale green run, non-GitHub check, pending run, or failed summary is not enough. GitHub's required branch protection remains active.

The lane intentionally does **not** gate on `factory:ready`, independent semantic-review approval, or `factory:changes-requested` status. Thus a factory-only PR stuck in a review loop can still merge once the above requirements pass. This exception does not apply to product changes.

### Scope boundaries

The allowlist covers designated factory controller/worker scripts, factory workflows, factory roster artifacts, factory tests, selected factory skills, and `docs/FACTORY*.md` / the canonical factory policy. Consult the actual regular expressions in the controller for exact names; **`.github/**` is not broadly allowed**.

In particular, the fast lane **excludes its own** switch, workflow, controller and contract test:

- `.github/factory-fast-merge.json`
- `.github/workflows/factory-fast-merge.yml`
- `.github/scripts/factory-fast-merge.py`
- `tests/test_factory_fast_merge.py`

Changes to these controls, mixed factory/product PRs, CI or production-deploy workflow changes, and anything outside the allowlist take the **normal review-gated path**. Do not split related security/policy modifications solely to evade this boundary.

## What the workflow actually does

The workflow serializes evaluations with the `factory-only-fast-merge` concurrency group. It checks out **trusted `main` only**, with checkout credentials not persisted, and never runs untrusted PR-head code with its write token.

For a candidate, the controller fetches the PR and complete file list, checks labels and ownership, reads genuine GitHub check runs and CI runs for the head SHA, then calls GitHub's squash merge API with `sha=<verified head>`. The SHA pin prevents merging a different commit if the branch moved. GitHub's required checks and mergeability enforcement remain in force.

A successful bot merge using `GITHUB_TOKEN` does not emit the usual push event. Therefore the merge script dispatches **Deploy Production** from its `finally` path after any successful merges, including if a later PR fails. The workflow also runs the post-merge issue-closure reconciliation sweep. The sweep's warning is not proof that the deployment failed, and a successful merge alone is not proof of end-to-end production acceptance.

## Troubleshooting without re-entering the slow lane

| Observed result | Correct next action |
| --- | --- |
| `{"enabled": false}` | Read the trusted-main switch. A switch change is itself **not** fast-merge eligible; use the normal review route. |
| Skipped: exact-head CI Summary not successful | Distinguish **pending** (let CI completion trigger the next attempt) from **failed** (repair code/checks and push a new head). Do not repeatedly rerun the gate. |
| Skipped: outside factory-only allowlist / incomplete file listing | Inspect changed paths and renames. Split genuinely independent product work into its normal PR; otherwise use normal review. |
| Skipped: missing labels, active owner or hold | Resolve real ownership/hold through the factory protocol, not by silently stripping labels. Once legitimately unowned, label change triggers evaluation. |
| Skipped: unmergeable, draft, fork, or untrusted author | Correct the actual PR property or use the normal route. A manual workflow dispatch cannot waive it. |
| Workflow succeeded but PR remains open | Read the `skipped` reason. A green workflow run means evaluation completed, **not** that a PR merged. |
| PR merged but deployment or issue closure is unclear | Verify the production dispatch and closure sweep independently; repair those processes rather than re-merging or inventing a deployment success. |

## Quick decision rule for agents

**Factory-only paths + trusted unowned PR + green exact-head CI → Factory-only Fast Merge.**

**Not factory-only, policy-control change, active lease/hold, or missing valid CI → do not force the fast lane.** Use the actual reason to determine whether to wait for an event, repair the PR, or use the regular merge path. Never claim a fast-lane merge without the GitHub merged result.
