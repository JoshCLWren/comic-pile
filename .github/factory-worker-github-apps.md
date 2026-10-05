# Worker GitHub App identities

Provenance key is the worker number, not the App slug. A model swap keeps the same App and the same name. Model and worker number stay in human-readable PR text. No `comicpile` prefix and no model name in the App slug. GitHub appends `[bot]`.

This change scaffolds **worker 48 / Mark Cordova** only. It does not create or register a GitHub App. Workers other than 48 keep using `PR_REBASE_TOKEN` for push and pull-request creation. Worker 48 also keeps using `PR_REBASE_TOKEN` until the App id, installation id, and private key are all present.

## Bootstrap (already done for worker 48)

Faker **40.40.0**, locale `en_US`, a brand-new `Faker()` per worker, `seed_instance(worker_number + 100)`, then `name()` as the first call. Worker 48's first `name()` is **Mark Cordova**. That name is persisted in `.github/factory-worker-github-apps.json`. Later reads must not re-roll it.

If the globally unique GitHub App name is taken when Josh creates the App, call `name()` once more on that same seeded instance, persist that second name, and stop.

```bash
python3 .github/scripts/factory_worker_github_app.py bootstrap-name 48
python3 .github/scripts/factory_worker_github_app.py bootstrap-collision 48
```

## What Josh does at login to finish the App

Borat does not create the App in this PR.

1. GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
2. Name: `Mark Cordova` (or the one persisted collision fallback). GitHub will append `[bot]`. Do not put `comicpile` or a model id in the name or slug.
3. Description: the `profile` string in `.github/factory-worker-github-apps.json` (it must say this is an autonomous ComicPile Factory worker).
4. Homepage: `https://github.com/JoshCLWren/comic-pile`.
5. Webhook: inactive.
6. Repository permissions, least privilege for push and pull-request creation:
   - Contents: Read and write
   - Pull requests: Read and write
   - Metadata: Read-only (GitHub requires it)
7. Installation: only this account. Install **only** on `JoshCLWren/comic-pile`.
8. Generate a private key. Do not commit it.
9. Repository Actions secrets (names are the contract; values stay in secrets):
   - `FACTORY_WORKER_48_APP_ID`
   - `FACTORY_WORKER_48_INSTALLATION_ID` (the id from the installation URL)
   - `FACTORY_WORKER_48_APP_PRIVATE_KEY` (PEM)
10. Optionally commit `app_id`, `app_login`, and `installation_id` into the worker 48 mapping entry. Do not re-roll `display_name`.

Until those three values exist, the factory runner's checkout still uses `PR_REBASE_TOKEN`, and worker 48 push plus `gh pr create` stay on `PR_REBASE_TOKEN` too. When they exist, only worker 48 switches push and PR creation onto a short-lived installation token. No other worker consults this mapping.

Worker Apps stay off every trusted-marker author path. `TRUSTED_FACTORY_APP_SLUGS` remains `github-actions` only. A worker App comment is not trusted even if GitHub reports a trusted association.
