# Factory-only fast merge

To enable or disable automatic factory-only merging, edit `.github/factory-fast-merge.json`:

```json
{"enabled": true}
```

Set `enabled` to `false` to switch it off. The switch, workflow and gate script are themselves excluded from the fast-merge allowlist, so their changes go through the normal merge route.

The **Factory-only Fast Merge** GitHub Action triggers on CI completion and pull-request events, with a five-minute scheduled fallback. It checks every modified path (including both sides of renames), requires a trusted same-repository PR author, non-draft and mergeable head, the `factory` and `factory:unowned` labels, no active owner or hold, and a successful authentic `CI Summary` plus successful CI workflow run at the exact SHA. It then squashes that head directly, bypassing semantic review. The required CI Summary branch rule is unchanged.

Mixed factory/product PRs, forks, active leases, blocked/security-labeled PRs, and changes to the fast-merge policy itself are ineligible. Unknown paths fail closed. This workflow checks out **main only** and never executes untrusted PR code with its write token.

After merging, it invokes existing post-merge reconciliation and the Deploy Production dispatcher. If CI is pending, failed, or unavailable, the PR remains open; it does not forge approvals or weaken branch protection.
