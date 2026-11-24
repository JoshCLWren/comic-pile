# Security documentation

ComicPile serves a static React frontend and native Rust API on Vercel, with
PostgreSQL hosted by Neon. There is no Python application server or FastAPI
middleware in the deployed request path.

## Production request boundary

```text
Internet -> Vercel edge (TLS) -> static frontend or native Rust API -> Neon PostgreSQL
```

`vercel.json` sends every `/api/*` request to native Rust and rejects unknown API
paths with a Rust JSON 404. The frontend is served as static output. TLS
certificates are provisioned and renewed by Vercel; certificate files are not
stored in this repository.

The native service requires `sslmode=require` in production and validates the
PostgreSQL server certificate and hostname. Do not enable an insecure TLS bypass.

## Secrets management

- Production secrets belong in Vercel project environment variables and GitHub
  Actions secrets. Local `.env` files must remain ignored.
- Use a long random JWT secret. Generate one with
  `openssl rand -base64 32` or `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`.
- Never commit secrets, put them in command arguments, or copy them into issues,
  logs, screenshots, browser environment variables or test artifacts.
- Use different credentials for development, CI and production. Rotate any
  credential that may have been exposed.
- ComicVine, SMTP, OAuth and cron credentials are server-side only; the frontend
  must never receive them.

See [deployment](docs/DEPLOYMENT.md) for the supported environment variables and
[database save/load](docs/DATABASE_SAVE_LOAD.md) for backup credentials.

## Browser-facing headers

The static HTML routes in `vercel.json` set the browser security policy. The
canonical values are generated route configuration, not a second copy maintained
by this document:

- Content-Security-Policy, including `frame-ancestors 'none'`, `form-action 'self'`
  and `frame-src 'none'`.
- Strict-Transport-Security with a two-year max-age, subdomains and preload.
- `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY`.
- `Referrer-Policy: strict-origin-when-cross-origin`.
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`.

Non-indexable HTML routes also receive `X-Robots-Tag: noindex, nofollow`. See
[the public SEO surface](docs/SEO_PUBLIC_SURFACE.md) for the indexing contract.
Do not claim that static HTML headers are applied by Rust API middleware.

## Authentication and authorization

- Product clients use `/api/v2/auth/*`. Access tokens are bearer credentials;
  refresh tokens are HttpOnly cookies, and state-changing browser requests use
  the CSRF token flow.
- The native auth handlers validate token signature, expiry, revocation,
  credential epoch and user existence. Ownership failures return 404 rather than
  revealing another reader's resource.
- Reading-history records are not authentication sessions. Password reset and
  credential revocation operate on auth state and must preserve reading history.
- Rate limits and durable login lockout are implemented in native Rust. See
  [rate limiting](docs/rate_limiting.md) for the authoritative controls.

## Logging and error handling

The native service logs method, route, status, timing and sanitized error kinds.
It does not log request bodies, authorization headers, cookies, reset tokens,
database URLs, SQL text or raw upstream error payloads. Production panic output
is redacted. Client errors use the documented JSON envelope without internal
exception details.

## Health and recovery

`GET /api/v2/health` is a process liveness probe and does not open a database
connection. A 200 response does not prove database readiness or successful
authenticated execution. Use a real data request and the migration planner for
those separate checks; see [operational health](docs/OPERATIONAL_HEALTH.md).

Before a production migration, take and verify a database backup. Schema
migrations are forward-only; a previous Vercel deployment is not proof that it
remains compatible with the current Neon schema.

## Containers and supply chain

Production runs on Vercel, not in an application-owned long-lived container.
The repository's Docker images are for CI and isolated browser/test stacks:

- `Dockerfile.ci` contains Python/Node tooling for repository checks; it is not a
  production runtime image.
- `native/roll-service/Dockerfile.audit` builds the Rust service and migration
  runner for the disposable UI-audit stack.

Do not describe these images as proof of production non-root execution or
read-only filesystem hardening. Those properties must be verified at the actual
managed-runtime boundary.

Before deployment, review dependency and image scan results appropriate to the
artifacts being released, for example:

```bash
cargo audit
docker scout cves <ci-or-audit-image>
```

A scanner must target the image actually built for the relevant workflow. Do
not scan a retired Python base image and treat that as production evidence.

## Incident response

1. Rotate affected Vercel, GitHub Actions, database, SMTP, OAuth, cron and
   provider credentials.
2. Review Vercel, GitHub, Neon and provider audit logs for unauthorized use.
3. Redeploy or restore only through the established production workflow after
   confirming schema compatibility.
4. Preserve secret-free evidence and record the affected revision, timestamps
   and mitigation in the existing incident or PR record.
5. Add a focused regression test for any corrected security defect.
