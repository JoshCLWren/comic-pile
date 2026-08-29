# Scripts

This directory holds **reusable operational tools** only. One-off data-fix
scripts, personal diagnostics, and single-use reading-order builders have been
moved to [`archive/scripts-oneoff/`](../archive/scripts-oneoff/) (git history
preserved via `git mv`).

## What stays here

These are tools that remain safe and useful to rerun:

- Backup/restore: `backup_postgres.sh`, `restore_postgres.sh`
- Database export/import: `export_db.py`, `import_db.py`, `clone_prod_to_local.py`
- OpenAPI tooling: `export_openapi_schema.py`, `generate_openapi_types.py`
- Seed and dev utilities: `seed_data.py`, `seed_dev_db.py`, `dev-all.sh`
- Factory/CI automation, lint/test helpers, and monitoring tooling
- Shared libraries used by other scripts: `comic_pile_api.py`, `wildstorm_chains.py`

If you are unsure whether a script is reusable or a fossil, check whether it is
referenced by CI, the Makefile, tests, or docs. Anything unreferenced that was
written for one specific data state belongs in `archive/scripts-oneoff/`.

## What moved to `archive/scripts-oneoff/`

One-time database patches, personal diagnostics, and single-purpose reading-order
builders. These were run against a specific collection state and are kept for
reference only. See `archive/scripts-oneoff/` for their archived documentation.