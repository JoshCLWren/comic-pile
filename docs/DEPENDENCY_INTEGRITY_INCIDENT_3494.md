<!-- docs-path-check: historical -->
# Dependency-integrity false negative on PR #3186 (issue #3494)

This is a point-in-time incident report. Paths that existed only in the
October 2026 tree are quoted as historical evidence; the controls adopted at
the end describe current `main`.

## Summary

PR [#3186](https://github.com/JoshCLWren/comic-pile/pull/3186) merged on
2026-10-06 at `22e5a6a` with a malformed **nested** lockfile in the final head
`8292506cedc41f2090d400012b15acf6186a1016`. CI reported 14 successful check
runs on that head. The malformed file was `frontend/pnpm-lock.yaml`; the
workspace-root `pnpm-lock.yaml` was clean. Every pnpm command in CI installed
from the root lockfile, so the nested file was copied into the checkout and
image but never parsed. No job validated it, and `CI Summary` aggregated only
the jobs it knew about, all of which were green.

## Exact evidence

| Evidence | Observation |
| --- | --- |
| `git show 8292506:frontend/pnpm-lock.yaml` | 48 conflict-marker lines, including the `msw` and `vitest` resolution blocks around lines 115–143. |
| `git show 8292506:pnpm-lock.yaml` | Zero conflict-marker lines; a well-formed pnpm v9 lockfile. |
| `git show 8292506:pnpm-workspace.yaml` | `packages: ['frontend']`, so pnpm resolves dependencies from the root lockfile only. |
| [CI job 112270549264](https://github.com/JoshCLWren/comic-pile/actions/runs/37463918535/job/112270549264) (Frontend Lint + Typecheck) | Checked out `refs/remotes/pull/3186/merge` at `a3fc4e9` (merge of head `8292506` into base `46a0f6055a4b3eeef090764ae41d60f93662b998`), then logged `Scope: all 2 workspace projects`, `Lockfile is up to date, resolution step is skipped`, and `Done in 5.8s using pnpm v10.15.0`. |
| [CI job 112270047815](https://github.com/JoshCLWren/comic-pile/actions/runs/37463918535/job/112270047815) (Build Docker Image) | The `frontend-deps` stage in the historical `Dockerfile.ci` copied only `package.json`, `pnpm-lock.yaml` and `pnpm-workspace.yaml` before `RUN pnpm install --frozen-lockfile`. `COPY frontend/ frontend/` happened later and never fed an install. |
| [CI job 112273869645](https://github.com/JoshCLWren/comic-pile/actions/runs/37463918535/job/112273869645) (CI Summary) | Checked ten named job results, all `success`, and emitted `All enabled CI jobs passed successfully!`. There was no dependency-integrity context to fail. |

The checked-out merge tree and the exact PR head therefore agree on the
defect: both contain the malformed nested lockfile. The green result is not a
stale status or a different SHA problem; it is an unvalidated file that pnpm
never reads.

## Local reproduction

Using pnpm 10.15.0 and isolated copies of the current root/frontend manifests:

| Fixture | `pnpm install --frozen-lockfile --lockfile-only --offline` | `check_dependency_integrity.py` |
| --- | --- | --- |
| Valid current manifest/lockfile pair | passes, lockfile unchanged | passes |
| Conflict markers inserted into the root lockfile | fails while parsing YAML | fails with file and line |
| Frontend manifest range bumped without lockfile update | `ERR_PNPM_OUTDATED_LOCKFILE` (`msw`: lockfile `^3.0.7`, manifest `^3.0.8`) | fails with the same range difference |
| Historical conflict blocks in nested `frontend/pnpm-lock.yaml`, valid root lockfile | **passes** — pnpm reads only the root lockfile | fails on the nested lockfile and each marker line |

The fourth row is the reproduced false negative: a frozen install alone cannot
detect this incident. The guard must inspect every workspace lockfile path.

## Root cause

1. The Dependabot repair produced a nested workspace lockfile with unresolved
   conflict markers while leaving the root lockfile valid.
2. pnpm treats the root `pnpm-lock.yaml` as authoritative for the whole
   workspace. `--frozen-lockfile` verified only that root file; the nested file
   was inert for installs but still part of the merged source tree.
3. The October CI workflow had no check that parsed, or even rejected, nested
   lockfiles in workspace packages.
4. `CI Summary` was the required aggregate context, but it could only check
   the jobs listed in its `needs`. A validation job that does not exist cannot
   make it fail.

## Why post-incident CI was still incomplete

Commit `5108ee4bf` (#5514) deleted the vestigial nested lockfile and added
`scripts/check_nested_lockfiles.sh` to `script-checks`. That closed the narrow
file-existence hole but left three gaps:

- `script-checks` is gated by `factory-scope` and is skipped on the
  factory-only fast path, so a lockfile edit in that path had no dependency
  check at all.
- It rejects nested lockfiles by name but does not parse root/workspace
  manifests or verify manifest-to-lockfile specifier consistency.
- It validates only the effective checkout. It does not archive and validate
  the exact PR head SHA, so a merge checkout and head can diverge without a
  second check.

## Controls adopted for this issue

- `scripts/check_dependency_integrity.py`: offline, deterministic validation
  of the root manifest, `pnpm-workspace.yaml`, `Dockerfile.ci`, every workspace
  manifest, and the root lockfile importers. It rejects conflict markers,
  malformed or duplicate-key data, nested workspace lockfiles, missing or
  inconsistent importer specifiers, and pnpm pin drift. `--root` lets the same
  code validate an arbitrary candidate tree.
- `.github/workflows/ci.yml`: a required `dependency-integrity` job with no
  path filters and no factory-scope gate. It unit-tests the guard, validates
  the effective checkout with the pinned pnpm version and a frozen
  `--lockfile-only` install, then archives and validates the exact PR head in
  its own tree. `CI Summary` fails when this job is unsuccessful, skipped, or
  indeterminate on both the fast path and the full path.
- `tests/test_dependency_integrity.py`: regression coverage for the historical
  `msw`/`vitest` conflict fixture, valid dependency bumps, specifier drift,
  missing importers, pnpm pin drift, duplicate manifest keys, and separate
  validation of base, exact PR head, and synthetic merge trees.

## Branch protection and merge-controller follow-up

No branch-protection rule or merge-controller change was made. The merge
controller consumes the required `CI Summary` context; making dependency
integrity a required input to that context is sufficient to stop a green
summary from masking this class of defect. If a future owner audit finds that
branch protection does not require `CI Summary` itself, that is an owner-level
configuration decision and is recorded here rather than creating a new issue
during the Rust-cutover backlog freeze.
