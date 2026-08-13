# Repository boundary

ComicPile keeps a single source repository. The frontend (React + Vite
+ TypeScript) and the API (FastAPI + SQLAlchemy + PostgreSQL) live in
the same monorepo with stricter package, ownership, and test
boundaries.

## Decision

The canonical decision, evidence, and re-evaluation trigger live at
[`docs/architecture/repository-boundary-decision.md`](architecture/repository-boundary-decision.md).

## TL;DR

- **One repository.** Do not split frontend and backend.
- **No published OpenAPI package.** The OpenAPI schema is generated
  in the same repo by `scripts/generate_openapi_types.py`.
- **No Vercel Preview environments.** Production deployment is
  `main`-only; `vercel.json` disables every other branch.
- **Re-evaluate** when `both_dirs` commits exceed 25% in any rolling
  90-day window, or when a published OpenAPI package is needed for a
  new external consumer.

## See also

- [Vercel deployment](VERCEL_DEPLOYMENT.md)
- [Vercel production architecture](VERCEL_ARCHITECTURE.md)
- [React architecture](REACT_ARCHITECTURE.md)
