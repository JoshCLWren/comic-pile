# Vercel production architecture

ComicPile deploys a static React frontend, native Rust API handlers, and a
transitional Python/FastAPI function from the same repository. The Rust-only
`/api/v2` cutover is tracked by #4335; this document describes deployed ingress,
not a claim that every route has already migrated.

## Production request boundary

Vercel builds the React application from the root `package.json` and publishes
`static/react` as static output. Requests for `/` and client-side application
routes are served without starting an API runtime.

In `vercel.json`, explicit native routes, including
`GET /api/v2/health`, `POST /api/v2/auth/login`, and supported Rust Roll,
issue, queue, and reading resources, route to `api/native_roll.rs` or
`api/native_issue.rs`. Remaining transitional `/api/*` requests still fall
through to `api/index.py` until their own cutover steps ship. A URL's v1/v2
segment does not by itself prove the executing language.

The public bare `/health`, `/docs`, `/redoc`, and `/openapi.json` URLs
return **404 at Vercel ingress**. They neither start Python nor return
`index.html` from the SPA fallback. Use `/api/v2/health` for production
liveness, and read the checked-in generated OpenAPI schema at
`native/contracts/v2-runtime.openapi.json` or the merged contract at
`frontend/src/generated/openapi.json`. Local FastAPI still exposes Swagger
and ReDoc for development.

Backend routes precede filesystem and SPA fallback rules, so unknown API
paths never return `index.html`. Static assets use Vercel's filesystem
boundary; non-file client-side routes return the SPA shell for React Router.

The root HTML response includes `X-ComicPile-Frontend: vercel-static`; native
API responses include `X-ComicPile-API-Runtime: rust`. These headers distinguish
actual frontend and Rust execution from a matching HTTP status alone.

## Security and caching

Static HTML receives the browser-facing CSP, HSTS, frame protection,
content-type protection, referrer and permissions policies. HTML is revalidated
so a new deployment is visible promptly. Fingerprinted Vite assets can be
cached independently.

## Local development

Local development is unchanged:

```bash
make dev
```

Vite proxies `/api` to local FastAPI; `app.main:app` may serve built SPA
files and the local `/health` and documentation surfaces. These local
endpoints are not the production ingress contract.

## Verification

After deploying `main`, inspect the static and native paths independently:

```bash
curl --silent --show-error --location --dump-header - --output /dev/null \
  https://comic-pile.vercel.app/

curl --silent --show-error --location --dump-header - \
  https://comic-pile.vercel.app/api/v2/health
```

The first response must include `X-ComicPile-Frontend: vercel-static`.
The second must return HTTP 200, `{"status":"ok"}`, and
`X-ComicPile-API-Runtime: rust`. The production deploy workflow independently
checks the rejected-login contract and Rust marker. Bare legacy health/docs
paths must return HTTP 404 without invoking either API runtime.
