# Scripts

This directory holds **reusable operational tools** only. One-off data-fix
scripts and single-use builders are deleted rather than archived; git history
keeps them.

## What stays here

These are tools that remain safe and useful to rerun:

- Backup/restore: `backup_postgres.sh`, `restore_postgres.sh`
- OpenAPI and client tooling (Node): `export_openapi_schema.mjs`, `generate_openapi_types.mjs`, `generate_native_client.mjs`
- Route generation/burndown (Node): `generate_route_burndown.mjs`, `generate_vercel_routes.mjs`
- Local/e2e helpers: `e2e_native_ingress.py`, `e2e_regression_select.py`
- Factory/CI automation, lint/test helpers, and monitoring tooling

If you are unsure whether a script is reusable or a fossil, check whether it is
referenced by CI, the Makefile, tests, or docs. Anything unreferenced that was
written for one specific data state should be deleted.
