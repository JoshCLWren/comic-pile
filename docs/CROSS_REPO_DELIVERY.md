# Cross-repository factory delivery

ComicPile's autonomous factory can deliver selected work to a small, allowlisted set of target repositories. The coordination/source repository is always `JoshCLWren/comic-pile`; the delivery/target repository is an allowlisted destination. The bootstrap target is `JoshCLWren/Latticery`.

## Allowlisted targets

Only these target repositories are accepted:

- `JoshCLWren/comic-pile` (default target; ordinary ComicPile-only delivery)
- `JoshCLWren/Latticery` (allowlisted cross-repository delivery)

A task may declare an allowed target repository. Arbitrary repository text from an issue body is never treated as authorization; `app/config.py:GitHubSettings.validate_target_repo()` and the `delivery_records` table check constraint enforce the allowlist at runtime and in the database.

## Credential boundary

ComicPile's workflow `GITHUB_TOKEN` remains the credential for ComicPile coordination. It is never replaced globally by a cross-repository PAT.

For operations whose target is `JoshCLWren/Latticery`:

- `LATTICERY_TOKEN` is read from the GitHub Actions repository secret of the same name.
- The credential is used only for the bounded Latticery checkout/push/PR operation that needs it.
- The token is never printed, persisted in the delivery ledger, logged, written to branches, embedded in issue bodies, or leaked into generated files.
- The token is never passed to agent/model prompts or subprocess environments that do not require GitHub authentication.
- Delivery to Latticery fails closed: if `LATTICERY_TOKEN` is unavailable, the operation raises `RuntimeError` and does not fall back to `GITHUB_TOKEN`.

Ordinary ComicPile work continues to use `GITHUB_TOKEN` and never requires `LATTICERY_TOKEN`.

## `LATTICERY_TOKEN` secret

- **Secret name**: `LATTICERY_TOKEN`
- **Secret type**: GitHub Actions repository secret on `JoshCLWren/comic-pile`.
- **Credential type**: a fine-grained personal access token (PAT) restricted to `JoshCLWren/Latticery` only.
- **Repository permissions**: the minimum scope required for branch/commit delivery and pull-request operations:
  - **Contents**: Read and write
  - **Pull requests**: Read and write
- No other repository or organization access is granted. The token is scoped to `JoshCLWren/Latticery` alone so it cannot mutate ComicPile or other repositories.

## Delivery ledger identity

Delivery records in the `delivery_records` table store full target-repository identity (`target_repository`, `target_branch`, `issue_number`, `target_pr_number`, `target_merge_sha`), so same-number issues and PRs across repositories are never confused. The ledger never contains credentials or tokens.

## Configuration

`app/config.py:GitHubSettings` owns the allowlist and credential selection:

- `LATTICERY_TOKEN` environment variable maps to `latticery_token`.
- `ALLOWED_TARGET_REPOS` environment variable can override the default allowlist.
- `get_credential_for_repo()` selects `LATTICERY_TOKEN` for Latticery and `GITHUB_TOKEN` for ComicPile, and fails closed when Latticery is requested without its token.