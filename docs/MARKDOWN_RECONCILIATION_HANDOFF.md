# Markdown reconciliation handoff — issue #5757

> **Status: point-in-time audit record, not current operating instructions.** The
> canonical Markdown files remain the instructions; this file records the audit,
> inventory accounting and delivery evidence required by issue #5757 acceptance
> criteria A19 and A28, and the repair of review finding F1 on PR #5835.
<!-- docs-path-check: historical -->

## Outcome and relationship to merged work

PR #5835 was opened against an older `main` to reconcile three stale ComicVine
documents. At the exact reviewed head `b963c3b9d82d0af1ec1554fe00901c406884a3d8`
those three edits are byte-identical to current `main`: merged PR #5846 (issue
#5842, "Retire ComicVine background metadata repair jobs, cron, dispatch and queue
machinery") delivered the same documentation changes first. The reconciled state
of every other confirmed example is also already present on `main`.

This handoff is this PR's unique deliverable: it records the tracked-Markdown
accounting, the sources of truth consulted, the validation results and the
remaining delivery discrepancies. Merging this PR adds that evidence; it does not
re-land business logic, API contracts, schemas or factory behavior.

**Stale-base artifact and its resolution.** At reviewed head `24ee72c` the branch
was 222 commits behind `main`, so the bare-head code-path guard reported three
paths in `COMICVINE_RUNTIME_FALLBACK.md` (the native ComicVine provider module,
twice, and the V8 ledger-retirement migration) as stale: those files exist on
`main` but were absent from the old branch snapshot. The `Docs code-path check`
job checks out `pull_request.head.sha`, so it failed on that bare head and the
`VERCEL_DEPLOYMENT.md` section conflicted with `main`. Per F1's first option the
branch was synchronized with current `main` (no-commit merge, conflict resolved
by keeping `main`'s retired-background-repair text plus this handoff's navigation
link). The resulting tree differs from `main` only by this handoff and its two
links; the code-path guard passes on the bare head and no conflict remains. No
`docs-path-check` suppression, test weakening or assertion change was used.

## Documents changed by this PR and stale claims corrected

| File | Stale claim removed | Correct current claim |
| --- | --- | --- |
| `docs/COMICVINE_HYDRATOR.md` | Eligible metadata refreshes use a durable repair queue and maintenance worker; link to the retired creator-repair-cadence anchor | Hydration completes inside the exact-issue request or an explicit authenticated `metadata:refresh` (Retry) request; link to the retired-background-repair anchor |
| `docs/COMICVINE_RUNTIME_FALLBACK.md` | A normal read enqueues `comicvine_metadata_refresh_requests`; a leased native worker drains it, with backfill and maintenance endpoints | A read derives `metadata_status` from freshness only; the ledger migration is recorded as retired; one bounded awaited fetch follows confirm/remap; `metadata:refresh` is the explicit Retry path |
| `docs/VERCEL_DEPLOYMENT.md` | Daily Vercel cron plus a four-times-per-hour GitHub Actions drain with `CRON_SECRET` activation and manual dispatch | Background repair is retired by #5842; `CRON_SECRET` remains only for the unrelated release-sync cron; no polling or automatic retry loop remains |
| `docs/README.md` | — | Adds a navigation link to this audit record so the generated-inventory/handoff evidence is discoverable |
| `docs/MARKDOWN_RECONCILIATION_HANDOFF.md` | — | New point-in-time audit record (this file) |

## Seven confirmed examples: reconciled on current main

| Canonical document | Prior drift in the issue | Current statement observed at this head |
| --- | --- | --- |
| `README.md` | FastAPI backend, `app/` layout, Python startup, v1 health | Quick start lists Docker, Rust, Node/pnpm and Python-tooling-only prerequisites; native Rust API at `http://localhost:8010/api/v2/health`; explicitly "no Python application runtime" |
| `docs/README.md` | "Current production truth" named FastAPI | Names a static Vite build, a single native Rust handler for `/api/*`, Neon PostgreSQL, the Rust refinery runner and unsupported Vercel Preview environments |
| `docs/ARCHITECTURE.md` | Python/FastAPI/SQLAlchemy backend, v1 canonical, FastAPI lifecycle | Native-Rust architecture, retained v1/unversioned aliases only where router/contract/ingress publish them, Alembic retired, historical Python section explicitly marked |
| `docs/API.md` | FastAPI-generated docs, v1 destination, combined Python/native OpenAPI | Native Rust same-origin JSON surface, generated contract sources of truth, no FastAPI/Swagger/ReDoc, retained aliases documented without directing new work to Python handlers |
| `docs/DEPLOYMENT.md` | FastAPI serving production API, old health checks | Vercel `main` deployment, Neon PostgreSQL, Rust migration runner and compatibility URL-prefix note; no stale Python health instructions |
| `docs/READING_LIST_RUNTIME.md` | Pre-activation Option E instructions, default-disabled switch, legacy execution | Reading Lists are the canonical owner-scoped Rust runtime under `/api/v2`; historical report harness carries its own supersession notice |
| `AGENTS.md` | Dated cutover instructions and remaining-Python-handler observations as active rules | Active engineering rules separated from explicitly historical cutover context; route burndown marked generated and bot-owned; current deployed runtime listed by owner |

## Sources of truth consulted

`vercel.json` (native ingress and catch-all), `Cargo.toml` (single workspace),
`native/roll-service/src/lib.rs` and `api/native_roll.rs` (route registrations),
`native/contracts/v2-runtime.openapi.json`,
`native/contracts/same-path-runtime.openapi.json`,
`docs/api/v2-route-inventory.json`, `native/migrate/migrations/`,
`frontend/src/services/api.ts`, `Makefile`, `.github/workflows/docs.yml`,
`docs/AUTONOMOUS_FACTORY_POLICY.md`, `docs/OBJECTIVE_FIRST_ENGINEERING_CONTRACT.md`
and the checked-in factory workflows. Production behavior claims come from these
checked-in sources and prior owner evidence; no credentialed or destructive
production verification was attempted in this review runtime.

## A19 — inventory accounting

Generated with `python3 scripts/generate_markdown_inventory.py --output
/tmp/MARKDOWN_INVENTORY_5757.md` (the same generator the Documentation workflow
publishes as an artifact). On the synchronized head `git ls-files '*.md'` reports
292 tracked Markdown files, including this handoff; the generator excludes
`docs/MARKDOWN_INVENTORY.md` so regeneration is idempotent. Disposition totals
counted from the generated 292-row table:

| Disposition | Files |
| --- | --- |
| keep (active/canonical) | 83 |
| historical — preserve | 199 |
| superseded — preserve with link | 8 |
| generated — test fixture | 2 |

Historical prefixes (`docs/issue-plans/`, `docs/changelog*`) and generated output
prefixes are excluded from the code-path guard by existing tooling, not by new
rules. No active document is left pointing at a retired Python API handler or a
deleted source path; the only remaining discrepancy is the duplicate-delivery
relationship (the reconciled doc content already landed on `main` through #5846),
which this PR retains solely as the A19/A28 audit evidence.

## A28 — validation and handoff

Checks observed in this review runtime on the synchronized tree:

- `python3 scripts/check_markdown_docs.py` — exit 0; "Validated 292 current
  Markdown files."
- `node scripts/check_doc_code_paths.mjs` — exit 0; "Doc code paths resolve in
  292 Markdown files." (the three stale paths from the old base are gone).
- `node --test scripts/check_doc_code_paths.test.mjs` — exit 0; 16 pass, 0 fail.
- `python3 scripts/generate_markdown_inventory.py --output
  /tmp/MARKDOWN_INVENTORY_5757.md` — exit 0; counts above.
- `git write-tree` diff against `origin/main` — only this handoff, the
  `docs/README.md` link and the `docs/VERCEL_DEPLOYMENT.md` link differ; the
  `git merge-tree` conflict and the `CONFLICTING` merge state are resolved.
- `python3 -m pytest` could not run: pytest is not installed in this runtime
  (`No module named pytest`); the Documentation workflow runs
  `tests/test_markdown_docs.py` and `tests/test_generate_markdown_inventory.py`
  in CI. No result is claimed for those two files locally.
- Not executed locally: `make dev` with a live PostgreSQL instance, browser E2E
  and any credentialed production request. These require services/credentials
  unavailable in this review runtime; no result is claimed for them.

At the prior bare head `24ee72c`, `gh pr checks` showed `Docs code-path check`
and `CI Summary` failing and `mergeable: CONFLICTING`; those failures are the
stale-base artifacts fixed by the synchronization recorded above. Remaining
discrepancies: PR #5835's reconciled doc content was already delivered by merged
#5846; this PR is retained only as the audit/handoff evidence required by A19 and
A28, plus the synchronization that makes the head self-consistent. Delivery must
follow the existing Rotisserie claim, exact-head CI, independent review and merge
gates; no factory policy, automation schedule, production business logic, API
contract or schema was changed here.

## A31 — maintenance rule

No new documentation system or broad keyword ban was added. The existing checks
(`check_markdown_docs.py`, `check_doc_code_paths.mjs`, the inventory generator and
the Documentation workflow) already cover links, anchors, code paths and
exhaustive accounting; point-in-time records stay valid through the established
historical/superseded notices.

## Criterion evidence index

| Criterion | Changed-file citation | Evidence summary |
| --- | --- | --- |
| A1 | this file | Problem recorded in the outcome section; docs drifted from the Rust runtime |
| A2 | this file | Audit-only outcome; no architecture or migration change |
| A3 | `docs/README.md`, this file | Seven confirmed examples mapped to their reconciled statements |
| A4 | this file | vercel.json, Cargo.toml and the zero-Python route inventory used as truth |
| A5 | this file | Inventory generator run and accounted in A19 |
| A6 | `docs/README.md`, this file | Root/index documents checked and index link added |
| A7 | this file | Architecture/API/deployment/reading sources consulted and mapped |
| A8 | this file | Reading List, roll and ComicVine guidance checked against sources |
| A9 | this file | Factory policy/workflow sources consulted; no new policy introduced |
| A10 | this file | Nested skill guidance covered by the tracked-Markdown inventory |
| A11 | this file | Disposition classification recorded in A19 |
| A12 | this file | Source-of-truth list records router, ingress, contracts and scripts |
| A13 | this file | Current Rotisserie/workflow integration used; no invented CLI flags |
| A14 | this file | Production claims limited to checked-in config; verification gap recorded |
| A15 | this file | API version and implementation language kept distinct in the API table |
| A16 | this file | Reading List described as canonical; Option E kept historical |
| A17 | this file | Python tooling/scripts distinguished from the removed Python runtime |
| A18 | this file | Generated contracts and tooling preferred over copied route tables |
| A19 | this file | 292 files accounted; 83/199/8/2 dispositions; exclusions recorded |
| A20 | this file | All seven examples reconciled on current main with paths |
| A21 | this file | README prerequisites/ports checked against Makefile; local limits recorded |
| A22 | `docs/MARKDOWN_RECONCILIATION_HANDOFF.md` | API doc agreement checked against generated contracts and callers |
| A23 | `docs/VERCEL_DEPLOYMENT.md` | Vercel/Neon, migration runner, health and preview statements verified |
| A24 | `docs/COMICVINE_HYDRATOR.md`, `docs/COMICVINE_RUNTIME_FALLBACK.md` | Migration-era queue/cron fallback guidance removed |
| A25 | this file | Agent guidance checked against current factory safeguards |
| A26 | `docs/README.md`, `docs/COMICVINE_HYDRATOR.md` | Added/repaired links use existing anchors; no dangling references added |
| A27 | this file | Local doc/link/code-path/generator/unit checks pass on the synchronized head; prior-head CI failures recorded as stale-base artifacts |
| A28 | this file | Documents, stale claims, sources, validation and discrepancies recorded |
| A29 | this file | Documentation workflow and existing checks reused |
| A30 | this file | Generator and code-path commands executed above |
| A31 | this file | No new guard; existing tooling retained |
| A32 | this file | Docs-only change; no business logic, API, schema or factory changes |
