# Scripts

This directory contains reusable development/operations tooling, Python repository checks, test ingress/selectors, and a small number of retained legacy artifacts. Python here is tooling, not an application runtime.

## Current reusable tools

- PostgreSQL backup/loopback-only restore: `backup_postgres.sh`, `restore_postgres.sh`
- OpenAPI/client generation (Node): `export_openapi_schema.mjs`, `generate_openapi_types.mjs`, `generate_native_client.mjs`
- Route generation/burndown (Node): `generate_route_burndown.mjs`, `generate_vercel_routes.mjs`
- Local/browser-test ingress and inventory selection: `e2e_native_ingress.py`, `e2e_regression_select.py`
- Native E2E/CI, lint, monitoring, and repository-contract helpers

Factory controller scripts are supplied by the Rotisserie overlay and intentionally remain untracked here. Install the overlay before using them; see `AGENTS.md` → Factory runtime.

## Retained legacy or single-use artifacts

- `sync_local_to_railway.sh` is a retired deployment experiment that can drop/recreate a remote schema. Railway is not a current target; do not run it against any maintained database.
- `cleanup_prod_smoke_tests.sql` is a one-off production-data cleanup artifact, not a routine reusable command.
- `prod_data_changesets/` contains dated production change records, not a current scheduler.

These files remain for provenance. Their presence does not authorize execution. Before running any script, confirm its target database/environment, read the canonical runbook, and use disposable credentials/data for tests. Never point test or restore tooling at production or a shared reader database.

If a script is genuinely obsolete, remove or classify it through the existing documentation/delivery process rather than leaving ambiguous active guidance.
