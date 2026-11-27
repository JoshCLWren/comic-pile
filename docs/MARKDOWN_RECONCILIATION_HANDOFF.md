# Markdown reconciliation handoff — issue #5757

> **Status: point-in-time audit record, not current operating instructions.** The canonical Markdown files remain the instructions. This record carries the inventory accounting, source evidence, validation results and unresolved discrepancies required by issue #5757. Historical records keep their provenance through the repository's established status markers.

<!-- docs-path-check: historical -->

## Outcome and relationship to merged work

The documentation reconciliation was delivered by two merged pull requests:

- PR #5759 reconciled the active runtime, API, deployment, product and factory documentation, extended the inventory generator to classify historical/superseded/generated files, and repaired the documentation-validation tooling.
- PR #5827 added local Markdown `#fragment` anchor validation to the existing `scripts/check_markdown_docs.py` guard, with focused regressions and a whole-repository no-broken-anchor check.

This change adds three closure artifacts: the audit evidence below, corrections for six residual active-document inaccuracies verified against checked-in sources, and a small extension to the existing Markdown guard (`find_stale_runtime_claims` in `scripts/check_markdown_docs.py`) that flags affirmative present-tense claims that FastAPI, SQLAlchemy or Alembic is the current runtime. The extension ignores negations, historical/superseded notices, explicit line overrides and fenced examples, so preserved provenance stays valid. It does not re-land the merged pull requests and changes no production business logic, API contract, database schema, factory behavior, automation schedule or generated route output. The audited tree is the current repository checkout; the handoff records what was actually observed here rather than claims about a divergent branch.

## Seven confirmed examples on the current tree

| Canonical document | Drift named by #5757 | Current reconciled statement | Evidence |
| --- | --- | --- | --- |
| `README.md` | FastAPI backend, `app/` layout, Python startup, v1 health | Quick start lists Docker, Rust, Node/`pnpm`, and Python tooling only; native Rust API on `localhost:8010` with `/api/v2/health` | `README.md` Quick start; `Cargo.toml`; `vercel.json` |
| `docs/README.md` | "Current production truth" named FastAPI | Static Vite build, one native Rust handler for `/api/*`, Neon PostgreSQL, Rust refinery runner, no maintained Vercel Preview environments | `docs/README.md` "Current production truth"; `vercel.json`; `native/migrate/` |
| `docs/ARCHITECTURE.md` | Python/FastAPI/SQLAlchemy backend, v1 canonical, FastAPI lifecycle | Native-Rust architecture; retained v1/unversioned aliases only where router, contract and ingress publish them; Alembic retired; Python-era sections explicitly historical | `docs/ARCHITECTURE.md`; `native/roll-service/src/lib.rs`; `docs/api/v2-route-inventory.json` |
| `docs/API.md` | FastAPI-generated docs, v1 destination, combined Python/native OpenAPI | Same-origin native JSON surface; generated contracts are the source of truth; no Swagger/ReDoc; retained aliases documented without directing new work to Python handlers | `docs/API.md`; `native/contracts/`; `frontend/src/services/` |
| `docs/DEPLOYMENT.md` | FastAPI served production, stale health instructions | Vercel deployment from `main`, Neon PostgreSQL, Rust migration runner, compatibility URL-prefix note; no Python health instructions | `docs/DEPLOYMENT.md`; `.github/workflows/`; `native/migrate/` |
| `docs/READING_LIST_RUNTIME.md` | Pre-activation Reading List engine instructions, default-disabled switch, legacy execution | Reading Lists are the canonical owner-scoped Rust runtime under `/api/v2`; migration-era report harness carries its own supersession notice | `docs/READING_LIST_RUNTIME.md`; `native/roll-service/src/` |
| `AGENTS.md` | Dated cutover notes and remaining-Python-handler observations presented as active rules | Active engineering rules separated from explicitly historical cutover context; generated route burndown marked bot-owned | `AGENTS.md`; `scripts/generate_route_burndown.mjs`; `vercel.json` |

No active document directs a contributor to a retired Python API handler or a deleted source path. The repository guards for local links, heading fragments and code paths are described in `docs/README.md`.

## Residual drift corrected in this change

These active-document inaccuracies remained after the two merged pull requests and were verified against checked-in sources before correction:

| Document | Stale claim | Corrected claim and evidence |
| --- | --- | --- |
| `README.md` | `.env.example` default database URL used `postgresql+asyncpg://` | Checked-in default is plain `postgresql://`; `.env.example:12-15`, `native/migrate/src/main.rs:21-26` |
| `docs/API.md` | `api-sessions.ts` still called retired v1 session list/get paths | Only v2 details/snapshots reads remain; `frontend/src/services/api-sessions.ts:5-21` |
| `docs/VERCEL_DEPLOYMENT.md` | The ComicVine Vercel cron entry was removed | A legacy cron entry is still declared but has no registered native route and falls through to the Rust 404; `vercel.json:6-15,329-334`, `api/native_roll.rs` |
| `docs/FACTORY_GITHUB_VISIBILITY.md` | Dispatcher recovery ran every 15 minutes | Installed workflow runs hourly at minute 37; `.github/workflows/fixed-model-factory-dispatch-recovery.yml:2-5` |
| `AGENTS.md`, `docs/READING_SESSION_NAMING.md` | `/api/session/`, `SessionListItem`, `SessionDetail` described as retained wire names | Those v1-era names are retired; current names are the `sessions` table, `session_id` path parameter, `SessionDetails`/`SessionSnapshotsResponse`; `frontend/src/types`, `frontend/src/services/api-sessions.ts` |
| `docs/ARCHITECTURE.md` | Tailwind configured by `frontend/tailwind.config.ts` | Tailwind 4 is CSS-first via `frontend/src/index.css` and `frontend/postcss.config.ts`; `frontend/package.json` |

## Sources of truth consulted

`vercel.json` (native ingress and catch-all), `Cargo.toml` and `rust-toolchain.toml`,
`api/native_roll.rs`, `native/roll-service/src/lib.rs`, `native/migrate/`,
`native/contracts/*.openapi.json`, `docs/api/v2-route-inventory.json`,
`frontend/src/services/`, `Makefile`, `package.json`, `.github/workflows/docs.yml`,
`.github/workflows/ci.yml`, `.rotisserie/config.toml`,
`docs/AUTONOMOUS_FACTORY_POLICY.md`, `docs/ISSUE_EXECUTION_PROTOCOL.md`,
`docs/FACTORY_GITHUB_VISIBILITY.md` and `docs/OBJECTIVE_FIRST_ENGINEERING_CONTRACT.md`.

Production behavior statements are drawn from checked-in configuration and prior owner evidence. No credentialed, destructive or fresh live Vercel/Neon probe was performed here; checked-in configuration is not presented as new deployment evidence.

## A19 — inventory accounting

Generated with `python3 scripts/generate_markdown_inventory.py --output /tmp/MARKDOWN_INVENTORY_5757.md`. The generator excludes `docs/MARKDOWN_INVENTORY.md` so regeneration is idempotent, and the generated inventory stays artifact-only.

At the audited `main` head, `git ls-files '*.md'` reports 291 tracked Markdown files. This record adds one point-in-time file, giving 292 files in the checked-out tree. Disposition totals for that 292-file tree:

| Disposition | Files |
| --- | --- |
| `keep` (active/canonical) | 83 |
| `historical — preserve` | 199 |
| `superseded — preserve with link` | 8 |
| `generated — test fixture` | 2 |

No row remains `review — classify`. The historical total includes 111 frozen changelog files and 37 issue-scoped plans; the two generated rows are the route-burndown fixture inputs and golden files. Historical prefixes (`docs/recovery/`, `docs/reports/`, `docs/issue-plans/`, `docs/changelog.d/`) and generated fixtures are excluded from drift enforcement by existing tooling, not by new rules.

## A28 — validation and handoff

Checks actually run in this checkout:

- `python3 scripts/check_markdown_docs.py` — exit 0, "Validated 292 current Markdown files."
- `node scripts/check_doc_code_paths.mjs` — exit 0, "Doc code paths resolve in 292 Markdown files."
- `node --test scripts/check_doc_code_paths.test.mjs` — exit 0.
- `python3 scripts/generate_markdown_inventory.py --output /tmp/MARKDOWN_INVENTORY_5757.md` — exit 0.
- Focused documentation tests in `tests/test_markdown_docs.py` and `tests/test_generate_markdown_inventory.py` — 31 pass through a stdlib harness; `pytest` is not installed in this worker runtime, so no `pytest` result is claimed locally.
- `python3 -m py_compile` on the changed Python tooling/tests — exit 0.
- `git diff --check` — clean.
- Tree scope: this handoff, the seven corrected active documents, the `docs/README.md` navigation link, the Markdown guard extension, and focused documentation tests are the only files changed relative to the audited head. A temporary-index `git write-tree` plus `git merge-tree --write-tree` against that head exits 0 with no conflict sections, because the changes are documentation, validation and test files only.

Not executed locally: `uv`-driven pytest, Ruff, ty, `bash scripts/lint.sh` (it exits early because Ruff is absent from this worker runtime), pnpm, a clean-checkout `make dev`/browser flow, and any credentialed production request. Exact-head CI and independent review remain required before delivery; this record does not claim either as complete.

## Remaining discrepancies (recorded, not changed here)

Carried forward from the PR #5759 handoff; these are outside the documentation-only delivery boundary of #5757:

- Core Reading List cycle writes return plain `409` while the builder expects structured `422`.
- Roll offer/bootstrap evaluates canonical inputs even while the rollout setting is off.
- Native server sessions/pending state conflict with #4405's sessionless/browser-owned target.
- A one-candidate pool shows Begin instead of Read Now; post-rate Roll does not auto-roll the next comic.
- ~~`frontend/src/services/api-sessions.ts` still calls retired v1 session list/get paths.~~ Resolved in `docs/API.md` and verified against `frontend/src/services/api-sessions.ts`; recorded here only as corrected provenance.
- `make verify` invokes a nonexistent `pytest` target; phase/Docker targets retain retired or unsafe behavior.
- `Production Deploy Wakeup` omits `source=factory-merge`.
- The installed state reconciler is hourly while policy requires a 15-minute sweep.
- Owner policy no-progress, lease and OmniRoute-cap values differ from runtime defaults.
- Several production Playwright scripts reference missing configs; `scripts/test_models.sh` can report the original model after testing a substitute.
- Some live native operations still lack complete utoipa declarations in the aggregate v2 contract.
- No dedicated native password-reset regression proves preservation of populated reading history.
- The README capture helper still expects a retired seeded-demo workflow.
- No fresh live Vercel/Neon probe was performed.

## Criterion evidence index

| Criterion | Evidence |
| --- | --- |
| Inventory of tracked Markdown (A19) | Disposition table above; `scripts/generate_markdown_inventory.py`; no `review — classify` rows |
| Seven confirmed examples | Table above against current canonical files and checked-in sources |
| Clean-checkout README/local testing | Reconciled in `README.md`, `LOCAL_TESTING.md` by PR #5759; no live clean-checkout run claimed here |
| API/versioning/Rust ingress | `docs/API.md`, `docs/api/v2-route-inventory.json`, `native/contracts/`, `vercel.json` |
| Deployment/recovery | `docs/DEPLOYMENT.md`, `docs/VERCEL_DEPLOYMENT.md`, `docs/DATABASE_SAVE_LOAD.md` |
| Reading/Roll/ComicVine | `docs/READING_LIST_RUNTIME.md`, `docs/COMICVINE_RUNTIME_FALLBACK.md`, reconciled by PRs #5759 and #5846 |
| Factory guidance | `AGENTS.md`, `docs/AUTONOMOUS_FACTORY_POLICY.md`, `docs/ISSUE_EXECUTION_PROTOCOL.md`, `docs/FACTORY_GITHUB_VISIBILITY.md` |
| Links, anchors, code paths | `scripts/check_markdown_docs.py`, `scripts/check_doc_code_paths.mjs`, PR #5827 |
| Validation | Commands and results in A28 above; exact-head CI and independent review still gated |
| Delivery handoff | This record plus the pull-request body; no policy, automation or production change |
