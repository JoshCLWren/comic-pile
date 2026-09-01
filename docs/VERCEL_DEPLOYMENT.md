# Vercel deployment

ComicPile uses Vercel for production only. The production branch is `main`.

## Deployment contract

- A push or merge to `main` may create one production deployment for that exact commit SHA.
- Pull requests and non-production branches must not create Vercel deployments.
- Pull requests are validated locally and through GitHub Actions.
- The React/Vite frontend is built as static output, while `/api/*` and the API documentation routes are served by FastAPI.
- Neon is the production PostgreSQL provider.

`vercel.json` disables Vercel Git deployments. The migration-aware
`.github/workflows/deploy-production.yml` workflow is the only supported deployment path.

The workflow listens for a direct `main` push and also retains factory-completion and scheduled
recovery triggers because merges performed by a GitHub workflow token do not reliably start another
push-triggered workflow. Those triggers share one concurrency group and perform an exact-SHA
preflight against Vercel. Once a `READY` production deployment exists for the current `main` SHA,
later automatic triggers exit without rerunning migrations or creating another deployment.
`workflow_dispatch` deliberately bypasses this deduplication as the explicit force-recovery path.

## Live-project verification

The Vercel project must track `main` as its Production Branch. Verify this in **Project Settings → Environments → Production → Branch Tracking**.

After this change is merged:

1. Push or update a non-production branch and confirm that no Vercel deployment is created.
2. Merge a validated change to `main` and confirm that one Production deployment is created.
3. Allow the factory-completion and scheduled recovery triggers to run and confirm they do not
   create another deployment for the same SHA.
4. Confirm the production alias still points to the successful `main` deployment.

Do not add Preview credentials, Preview databases, Preview Redis instances, or Preview-specific runtime branches. Disposable service instances used by local development or GitHub Actions are separate from Vercel Preview and remain supported.
