# Deployment

ComicPile has one supported production deployment: Vercel, sourced from the `main` branch.

## Production architecture

- Vercel serves the built React/Vite frontend as static output.
- FastAPI handles the intentional API routes and OpenAPI document.
- Neon provides PostgreSQL.
- Remote Redis caching is disabled by default while its command budget and invalidation design are being corrected.
- Pull requests are validated locally and in GitHub Actions. ComicPile does not provision or maintain Vercel Preview environments.

## Production delivery

Merges to `main` are the production source. The production workflow runs the required database migration against Neon before deploying the application to Vercel.

Do not add Fly.io, Railway, or another hosting target without a new product decision and an explicit migration plan. Historical references in the changelog describe past deployments and are not active operating instructions.

## Local development

Use `make setup` for the local environment, `make dev` for the frontend and API development servers, and `make verify` for the complete local verification suite. Local development and GitHub Actions remain independent from production deployment configuration.
