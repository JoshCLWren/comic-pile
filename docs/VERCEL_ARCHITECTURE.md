# Vercel production architecture

ComicPile deploys a static React frontend and a single native Rust API handler
from the same repository. `vercel.json` is generated from the route fragments
and the inventory. The production workflow regenerates it and strips retired
function entries before deployment; the checked-in generated file can briefly
retain those entries until the bot-owned regeneration lands. API version is not
implementation language.

## Production request boundary

Vercel builds the React application from the root `package.json` and publishes
`static/react` as static output. Requests for `/` and client-side application
routes are served without starting an API runtime.

In `vercel.json`, explicit native routes — including `GET /api/v2/health`,
`POST /api/v2/auth/login`, and the Roll, issue, queue, and reading resources —
route to the single `api/native_roll.rs` function. A catch-all routes every
other `/api/*` request there as well, where it answers with a Rust JSON 404.
No Python function is deployed. A URL's v1/v2 segment does not by itself prove
the executing language; check the inventory in
[`api/v2-route-inventory.json`](api/v2-route-inventory.json).

The public bare `/health`, `/docs`, `/redoc`, and `/openapi.json` URLs
return **404 at Vercel ingress**. They neither start a runtime nor return
`index.html` from the SPA fallback. Use `/api/v2/health` for production
liveness, and read the checked-in generated OpenAPI schemas at
`native/contracts/v2-runtime.openapi.json` and the merged contract at
`frontend/src/generated/openapi.json`.

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

```bash
make dev
```

Vite serves the frontend on `:5173` and proxies `/api` to the native Rust
service on `:8010`, resolving each request against the same ingress rules
derived from `vercel.json`. The native service serves `GET /health` and
`GET /api/v2/health` locally; there is no local FastAPI app or Swagger surface.
These local endpoints are not the production ingress contract.

## Verification

After deploying `main`, inspect the static and native paths independently:

```bash
curl --silent --show-error --location --dump-header - --output /dev/null \
  https://comic-pile.vercel.app/

curl --silent --show-error --location --dump-header - \
  https://comic-pile.vercel.app/api/v2/health
```

The first response must include `X-ComicPile-Frontend: vercel-static`.
The second must return HTTP 200 with `status: "ok"`, build/process identity fields,
and `X-ComicPile-API-Runtime: rust`. The production deploy workflow checks the
revision, package and compiler identity as well as the status. Bare legacy
health/docs paths must return HTTP 404 at the Rust catch-all without starting a
database-backed runtime.
