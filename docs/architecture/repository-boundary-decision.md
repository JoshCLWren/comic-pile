# Repository / package boundary decision — issue #640

> **Status:** Decided. Owner: ComicPile engineering. Re-evaluate when the
> measurable trigger in §6 fires.
>
> **Decision:** **Keep one repository** with **stricter package,
> ownership, and test boundaries** (Option 3). Do not split frontend and
> backend into separate repositories, and do not add a published
> OpenAPI package. Do not add Vercel Preview environments.

## 1. Scope and audience

This document is the canonical record of the repository / package
boundary decision required by issue [#640](https://github.com/JoshCLWren/comic-pile/issues/640).
It exists so future readers can find the decision, the evidence behind
it, and the trigger that should cause it to be revisited. It is the
single source of truth that the architecture, deployment, and React
documentation cross-link.

The decision lives at `docs/architecture/repository-boundary-decision.md`
and is summarised by the short landing page `docs/REPO_BOUNDARY.md`.

## 2. Problem

ComicPile's frontend (React + Vite + TypeScript) and backend
(FastAPI + SQLAlchemy + PostgreSQL) have always lived in the same
source repository. The question this issue asks is: should they stay
together after the prerequisite performance and frontend-architecture
work has substantially completed?

The question is not "is the monorepo dirty today?" — the prerequisite
work has already cleaned a large fraction of it (bounded Roll bootstrap,
generated OpenAPI types, bounded blocked/snoozed/stale summaries,
bounded queries, delta-based snapshots, batched blocked explanations,
etc.). The question is whether splitting the repository now would
deliver a benefit proportional to the coordination cost.

## 3. Out of scope

These items were already decided before this issue and are not
re-opened here:

- **Vercel Preview environments are out of scope.** #862 and PR #863
  resolved the deployment boundary: `/` and client-side routes are
  served as static Vercel output (`X-ComicPile-Frontend: vercel-static`),
  while `/api/*`, `/openapi.json`, `/docs`, `/redoc`, and `/health` are
  served by the FastAPI function. `vercel.json` disables deployments
  from every branch except `main`. No Preview credentials, Preview
  databases, Preview Redis instances, or Preview-specific runtime
  branches are permitted.
- **The static-frontend / API-function routing work completed by
  #862/#863 is not revisited.**
- **Repository separation is not used as a substitute for endpoint
  optimisation.** The prerequisite work already eliminated the N+1
  issue-count queries (#693), the full-library undo snapshots (#694),
  the universal `useThreads()` fan-out (#695, in flight), and the
  O(n²) queue repositioning (#699).
- **Authentication, CSRF, and secret handling are not weakened.** The
  app's async-only PostgreSQL rule (see `AGENTS.md`) and the canonical
  auth recovery flow remain in place.

## 4. Options considered

### Option 1 — Cleaned monorepo

Continue with one repository, no new package boundary, and rely on the
already-completed performance / frontend cleanup.

### Option 2 — Split frontend and API repositories around a published OpenAPI contract

Publish the OpenAPI schema as a separate package; move the React
frontend into its own repository; keep the FastAPI backend in the
existing repository; cross-reference the two via the published
contract. Each repository ships its own release cadence.

### Option 3 — Single repository with stricter package, ownership, and test boundaries

Continue with one repository, but adopt the explicit boundaries that
Option 1 leaves implicit:

- frontend code lives under `frontend/src/{components,pages,hooks,services,query,contexts,test,unit,generated}/`
  with screen-specific service modules (`api-roll.ts`, `api-issues.ts`,
  `api-dependencies.ts`, etc.) that each own their generated OpenAPI
  fragment;
- backend code lives under `app/{api,models,schemas,services,middleware}/`
  and `comic_pile/` with screen-aligned routers (`/api/v1/threads`,
  `/api/v1/dependencies`, `/api/v1/roll`, `/api/v1/issues`,
  `/api/v1/releases`);
- generated OpenAPI artifacts live at `frontend/src/generated/` and are
  refreshed by `scripts/generate_openapi_types.py` in the same repo;
- tests are aligned to the surface (`tests/` for backend, `frontend/src/test/`
  for Playwright, `frontend/src/unit/` for Vitest, `scripts/tests/` for
  repository tooling);
- the OpenAPI schema and TypeScript types are checked-in artifacts that
  drift-detect in CI via `python scripts/generate_openapi_types.py --check`.

## 5. Evidence

### 5.1 Coupling snapshot

The numbers below come from `scripts/coupling_metrics.py`, which
classifies each commit in the rolling window by which surfaces it
touches. The tool is reproducible (`pytest scripts/tests/test_coupling_metrics.py`)
and the snapshot is regenerated as part of any future revision of this
decision.

#### Coupling snapshot (last 12 months)

| Bucket | Commits | Share |
|---|---:|---:|
| `both_dirs` | 151 | 6.9% |
| `frontend_only` | 648 | 29.6% |
| `generated_only` | 8 | 0.4% |
| `backend_only` | 419 | 19.1% |
| `infra_only` | 569 | 26.0% |
| `docs_only` | 180 | 8.2% |
| `other` | 217 | 9.9% |

**Total commits measured:** 2192

#### Coupling snapshot (last 6 months)

| Bucket | Commits | Share |
|---|---:|---:|
| `both_dirs` | 113 | 8.5% |
| `frontend_only` | 562 | 42.3% |
| `generated_only` | 8 | 0.6% |
| `backend_only` | 140 | 10.5% |
| `infra_only` | 323 | 24.3% |
| `docs_only` | 64 | 4.8% |
| `other` | 120 | 9.0% |

**Total commits measured:** 1330

#### Coupling snapshot (last 3 months)

| Bucket | Commits | Share |
|---|---:|---:|
| `both_dirs` | 37 | 4.7% |
| `frontend_only` | 343 | 43.8% |
| `generated_only` | 8 | 1.0% |
| `backend_only` | 102 | 13.0% |
| `infra_only` | 184 | 23.5% |
| `docs_only` | 54 | 6.9% |
| `other` | 56 | 7.1% |

**Total commits measured:** 784

The trend across all three windows is the same: commits that touch both
`frontend/` and backend code are a small single-digit-to-low-double-digit
share. Most commits touch exactly one surface.

### 5.2 What "both_dirs" actually contains

The commits that touch both surfaces in the last six months are
dominated by:

- API contract normalisations (e.g. `/api/v1/*` aliases, canonical
  auth routes);
- New product features that introduce a backend endpoint and a
  consuming UI simultaneously (e.g. release ledger API, ComicVine
  issue intelligence, dependency-guided roll recovery, continuity
  readiness evaluation, dependency-chain viewer);
- Generated OpenAPI artifact refreshes that ship in the same commit as
  the backend change that triggered them (see `git log --stat` on
  `frontend/src/generated/openapi.json`).

None of these require a repository split: they need a single coordinated
pull request, which is the natural unit of review in a single repo.

### 5.3 Complexity matrix

| Concern | Option 1 (monorepo) | Option 2 (split repos + OpenAPI pkg) | Option 3 (monorepo + strict boundaries) |
|---|---|---|---|
| CI duplication | None — one workflow per concern. | High — duplicate lint, typecheck, Vitest, Pytest, Playwright, OpenAPI publish workflows. | None — one workflow per concern. |
| Release coordination | Single PR per release. | Two PRs per release; version negotiation across published OpenAPI. | Single PR per release; in-repo OpenAPI regeneration. |
| Rollback complexity | One revert; one Vercel deploy. | Two reverts; risk of API ahead of frontend or vice versa. | One revert; one Vercel deploy. |
| Observability | One Vercel project; one FastAPI function; unified logs. | Two Vercel projects OR one project with split log streams; cross-repo trace correlation. | One Vercel project; one FastAPI function; unified logs. |
| Local development | `make dev` (Vite + FastAPI on one port). | Two `git clone`s, two package managers, two dev servers, manual OpenAPI link. | `make dev` (Vite + FastAPI on one port). |
| Contract management | In-repo OpenAPI schema + checked-in generated TS. | Published OpenAPI package; risk of drift between API repo and consumer version pin. | In-repo OpenAPI schema + checked-in generated TS + `--check` drift gate. |
| Factory execution | One claim lease, one PR, one merge. | Two claim leases, two PRs, coordinated merge; coordination errors compound. | One claim lease, one PR, one merge. |
| Auth / CSRF / secrets | Existing single-app model remains. | Cross-repo secret and CSRF coordination; risk of secret duplication or split. | Existing single-app model remains. |
| Async-only PostgreSQL rule | One `app/config.py`, one Alembic env. | Two `app/config.py` rewrites OR a shared utility package; Alembic split. | One `app/config.py`, one Alembic env. |

### 5.4 Deployment model compatibility

ComicPile's Vercel deployment is already a two-path system:

- `/` and client-side routes → static Vercel output (`static/react/`).
- `/api/*`, `/openapi.json`, `/docs`, `/redoc`, `/health` → the FastAPI
  function (`api/index.py`).

There is no per-route artifact duplication to justify a repository
split: the static frontend is emitted from `package.json` and the API
function is emitted from `api/index.py`, both from the same `main`
branch. A split repository would force each half to publish a separate
artifact, and then the boundary that already lives in `vercel.json`
would have to be re-implemented by a deployment system.

### 5.5 Performance work status

The prerequisite work is largely complete and the remaining items do
not change the boundary decision:

- Closed performance prerequisites: #693, #694, #695, #697, #698, #699.
- Closed frontend-state prerequisites: #701, #702, #705, and the
  completed foundation (bounded blocking, Roll/rating bootstrap,
  Thread Details, and a generated OpenAPI fragment per screen).
- Open prerequisites: #696 (incremental Queue pagination epic), #700
  (production perf budget validation), #703 (universal `useThreads`
  replacement after #696 and #702), #704 (Roll and Queue route
  decomposition), #706 (bounded, cancellable prefetch). None of these
  requires a repository split, and all of them strengthen the
  Option-3 in-repo package boundaries.

## 6. Decision

ComicPile **keeps a single source repository** (Option 3: monorepo
with stricter package, ownership, and test boundaries). The static
frontend and API function continue to share `main` and a single Vercel
project, exactly as decided in #862 / PR #863. No published OpenAPI
package is added. No Vercel Preview environments are added.

### 6.1 Why not Option 2

Option 2 is rejected by the evidence:

- Only ~5–8% of commits in any 3-, 6-, or 12-month window touch both
  surfaces, so the coordination cost (two PRs, two merges, version
  negotiation) is not justified by the coupling rate.
- The OpenAPI schema is already generated in the same repo by
  `scripts/generate_openapi_types.py`; a published-package split would
  add a release artifact, drift-detection, and dependency pin
  management without removing any existing friction.
- The Vercel deployment model already separates the two surfaces at
  build time; there is no per-route duplication that a repository
  split would resolve.

### 6.2 Why Option 3 instead of Option 1

Option 1 is also viable, but Option 3 codifies the boundaries that
the prerequisite work has already been moving toward. It makes the
existing in-repo cleanup explicit in the documentation, so new
contributors can find the boundaries without reverse-engineering them
from the file tree.

### 6.3 Trigger for re-evaluation

Re-open this decision when **either** of the following measurable
triggers fires:

- `both_dirs` share exceeds 25% of commits in any rolling 90-day window
  as measured by `scripts/coupling_metrics.py --months 3`.
- The team needs a published OpenAPI package to support a new external
  consumer (currently none exist; ComicPile is single-consumer).

If neither trigger has fired, the decision stands. Re-evaluation does
not require splitting the repository; it only requires regenerating
the snapshot and comparing against §5.1.

## 7. Implementation

This decision is implemented by the following changes:

1. New `scripts/coupling_metrics.py` — reproducible coupling
   measurement tool. Emits text, Markdown, or JSON.
2. New `scripts/tests/test_coupling_metrics.py` — pins the surface
   classification rules.
3. New `tests/test_repository_boundary_decision.py` — pins the
   cross-link invariants between this document and the architecture,
   deployment, and React docs.
4. New `docs/REPO_BOUNDARY.md` — short landing page.
5. Cross-link additions in `docs/VERCEL_DEPLOYMENT.md`,
   `docs/VERCEL_ARCHITECTURE.md`, `docs/REACT_ARCHITECTURE.md`, and
   `README.md`.

No staged implementation issue is opened because the decision is **not
to split**. The follow-up that *would* have been opened (Option 2)
becomes unnecessary; the follow-up that *should* happen in Option 3
(stricter in-repo boundaries) is already in flight as part of the
prerequisite campaign.

## 8. Acceptance criteria checklist

Mapping to the original #640 acceptance criteria:

- [x] Measure frontend/backend change coupling after #641 is substantially complete. → §5.1.
- [x] Compare CI, release, rollback, observability, local-development, and contract-management complexity for each option. → §5.3.
- [x] Explicitly document that Vercel Preview environments are out of scope. → §3.
- [x] Make one explicit repository-boundary decision. → §6.
- [x] If a split is selected, open a staged implementation issue with rollback criteria. → §7 (decision was Option 3, so no split issue is opened).
- [x] Update architecture documentation with the decision. → §7 and cross-links.

## 9. Cross-links

- [`docs/REPO_BOUNDARY.md`](../REPO_BOUNDARY.md) — short landing page.
- [`docs/VERCEL_DEPLOYMENT.md`](../VERCEL_DEPLOYMENT.md) — deployment contract and Preview out-of-scope statement.
- [`docs/VERCEL_ARCHITECTURE.md`](../VERCEL_ARCHITECTURE.md) — production request boundary.
- [`docs/REACT_ARCHITECTURE.md`](../REACT_ARCHITECTURE.md) — frontend architecture and package boundaries.
- [`scripts/coupling_metrics.py`](../../scripts/coupling_metrics.py) — reproducible coupling tool.
- [`scripts/tests/test_coupling_metrics.py`](../../scripts/tests/test_coupling_metrics.py) — classifier regression tests.
- [`tests/test_repository_boundary_decision.py`](../../tests/test_repository_boundary_decision.py) — cross-link invariants.
