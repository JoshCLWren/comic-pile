# Scripts

This directory holds **reusable operational tools** only. One-off data-fix
scripts, personal diagnostics, and single-use reading-order builders have been
moved to [`archive/scripts-oneoff/`](../archive/scripts-oneoff/) (git history
preserved via `git mv`).

## What stays here

These are tools that remain safe and useful to rerun:

- Backup/restore: `backup_postgres.sh`, `restore_postgres.sh`
- OpenAPI and client tooling (Node): `export_openapi_schema.mjs`, `generate_openapi_types.mjs`, `generate_native_client.mjs`
- Route generation/burndown (Node): `generate_route_burndown.mjs`, `generate_vercel_routes.mjs`
- Local/e2e and verification helpers: `e2e_native_ingress.py`, `verify_wildstorm_reading_order.py`, `production_schema_audit.py`, `export_roll_test_schema.py`
- Factory/CI automation, lint/test helpers, and monitoring tooling
- Shared libraries used by other scripts: `comic_pile_api.py`, `wildstorm_chains.py`

If you are unsure whether a script is reusable or a fossil, check whether it is
referenced by CI, the Makefile, tests, or docs. Anything unreferenced that was
written for one specific data state belongs in `archive/scripts-oneoff/`.

## What moved to `archive/scripts-oneoff/`

One-time database patches, personal diagnostics, and single-purpose reading-order
builders. These were run against a specific collection state and are kept for
reference only. See `archive/scripts-oneoff/` for their archived documentation.