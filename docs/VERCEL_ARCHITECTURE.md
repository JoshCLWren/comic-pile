# Vercel production architecture

ComicPile deploys one static frontend and one Python API function from the same repository.

## Production request boundary

Vercel builds the React application from the repository root `package.json` and publishes
`static/react` as static output. Requests for `/` and client-side application routes are served
from that output without importing or starting FastAPI.

The following paths are routed to the API-only Python entry point in `api/index.py`:

- `/api` and every `/api/*` route, including `/api/v1/*`
- `/openapi.json`
- `/docs`
- `/redoc`
- `/health`

Backend routes are declared before the filesystem and SPA fallback rules so an unknown API path
cannot return `index.html`. Static assets are served by Vercel's filesystem boundary.

Frontend HTML is served in two SEO-correct ways rather than one catch-all to `index.html`:

- Each non-parameterized route (`/login`, `/queue`, `/cbl-sources`, …) is rewritten to the
  build-generated `<route>.html` metadata file. Those files carry the route's own title,
  description, and `noindex, nofollow`, so crawlers never see the landing page head on an
  authenticated route.
- Every other non-file path (parameterized routes such as `/thread/:id`, legacy sources such as
  `/threads/:id`, and unknown paths) is sent to the shared noindex `spa.html` fallback shell.
  It boots the same React application but has no canonical link, no landing JSON-LD, and
  `noindex, nofollow`.

Both branches set `X-Robots-Tag: noindex, nofollow`; only `/` is served `index.html` without it.
The routing rules live in `vercel.json` and are regression-tested by
`frontend/src/unit/seoVercelRouting.test.ts` and `tests/test_vercel_seo_routing.py` because, on
production, SPA requests never reach FastAPI.

The static HTML response includes `X-ComicPile-Frontend: vercel-static`. This is the production
evidence that `/` did not pass through the FastAPI function. The API function is created with
`create_app(serve_frontend=False)`, so it does not mount frontend files or register SPA routes.

## Security and caching

Static HTML receives the same browser-facing security policy used by FastAPI, including CSP, HSTS,
frame protection, content-type protection, referrer policy, and permissions policy. HTML is always
revalidated so a new deployment is visible promptly. Vercel serves fingerprinted Vite assets from
the static output boundary and can cache them independently.

## Local development

Local development remains unchanged:

```bash
make dev
```

Vite serves the frontend and proxies `/api` to FastAPI. The normal `app.main:app` application still
uses `serve_frontend=True`, preserving built-SPA serving for local production-build tests and other
non-Vercel runtimes.

## Verification

After deploying a branch or main, compare static and API paths independently:

```bash
curl --silent --show-error --location --output /dev/null \
  --dump-header - \
  --write-out 'ttfb=%{time_starttransfer}s total=%{time_total}s\n' \
  https://comic-pile.vercel.app/

curl --silent --show-error --location --output /dev/null \
  --dump-header - \
  --write-out 'ttfb=%{time_starttransfer}s total=%{time_total}s\n' \
  https://comic-pile.vercel.app/openapi.json
```

The root response must include `X-ComicPile-Frontend: vercel-static`. The API response must not.
After an idle period, root TTFB should remain materially below the former 8.5-second Python cold
start baseline, with a target below one second from a nearby Vercel edge.
