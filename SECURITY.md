# Security Documentation

Comic Pile's maintained production deployment is Vercel static frontend output plus the native Rust API (`api/native_roll.rs`) and Neon PostgreSQL. Python is not an application runtime. The repository's Docker Compose files are for local development, disposable tests, CI, or rendered audits; they are not the production hosting architecture.

## Production trust boundaries

```text
Internet → Vercel edge (TLS) → static React assets / native Rust API → Neon PostgreSQL
```

- Vercel terminates public TLS. The native production configuration requires PostgreSQL `sslmode=require` and validates certificates/hostnames.
- Browser API requests use bearer access tokens, an HttpOnly refresh cookie, and double-submit CSRF protection for authenticated state-changing requests.
- Handlers enforce owner-scoped access and bounded input before database work. Missing and foreign-owned resources both return 404.
- The standalone native service binds to loopback by default and refuses non-loopback development binds. Production binding and credentials are deployment configuration, not source defaults.
- Neon is reachable only through the configured connection URL. Do not expose PostgreSQL directly to the public internet.

## Secrets

Production secrets belong in Vercel project environment variables and GitHub Actions secrets. Local `.env` files are ignored and must never be committed.

- Generate strong random secrets (32+ bytes), for example with `openssl rand -base64 32`.
- Use different credentials for development, CI, and production.
- Rotate credentials after suspected exposure and redeploy so processes pick up the new values.
- Never put secrets in command arguments, URLs committed to Git, logs, fixtures, issue comments, or PR text.
- The local Compose passwords are disposable development placeholders, not production credentials.

See `.env.example`, `native/roll-service/src/config.rs`, and `docs/DEPLOYMENT.md` for the supported variable names and production workflow.

## Browser security headers

The built SPA's response headers are configured in `vercel.json`: Content Security Policy, HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, Referrer Policy, and Permissions Policy. These headers belong to the Vercel static-route contract; do not assume a function response inherits them.

Recorded gap: native API responses do not currently emit that static CSP/HSTS header set. The native boundary adds its runtime marker and returns JSON errors without credentials, SQL, reset tokens, provider secrets, or raw upstream payloads. Authentication, CSRF, ownership checks, bounded parsing, and sanitized logging are enforced in Rust.

## Rate limiting and lockout

There is no global SlowAPI/FastAPI middleware. Current native controls are scoped:

- process-local, bounded authentication throttles keyed by endpoint/client IP or refresh-token digest;
- durable PostgreSQL failed-login lockout per username and client IP under advisory locks;
- outbound GitHub issue-filing limits; and
- ComicVine repair backoff/defer/fail behavior for provider throttling.

See `docs/rate_limiting.md` and `native/roll-service/src/auth/handlers.rs` for exact limits and test-mode behavior.

## Health and operational evidence

`GET /api/v2/health` is dependency-free process liveness. It does not prove database readiness. Production responses include Rust runtime/build/process identity, and deployment smoke checks verify the expected source revision. Verify database readiness with a real authenticated data request or the migration planner.

See `docs/OPERATIONAL_HEALTH.md`, `docs/VERCEL_ARCHITECTURE.md`, and `docs/DEPLOYMENT.md`.

## Local and CI containers

`docker-compose.yml` defines only PostgreSQL and pgAdmin for local development. Disposable test/audit topologies run the native Rust service and built frontend. `Dockerfile.ci` is a root-running CI tooling image, not a production application image. Do not reuse the retired Python application container or its `HEALTHCHECK` instructions.

## Vulnerability and dependency review

Use the tools configured for the actual stack, for example:

```bash
cargo audit
pnpm audit
git-secrets --scan
```

Review Dependabot and repository CI failures before deployment. Do not treat a Python base-image scan as evidence for the deployed Rust function.

## Deployment checklist

- [ ] Production secrets are stored only in Vercel/GitHub secret stores.
- [ ] The database URL requires TLS and the application and migration runner target the same database.
- [ ] Required exact-head CI and independent review pass.
- [ ] `/api/v2/health` reports the expected Rust source revision.
- [ ] A real authenticated request succeeds; liveness alone is not database proof.
- [ ] The previous READY production deployment remains available as the rollback candidate.
- [ ] No credentials or reader data appear in logs, artifacts, or PR comments.

## Incident response

### Compromised secrets

1. Rotate the affected Vercel and GitHub Actions secrets.
2. Revoke affected credentials/tokens and inspect audit logs.
3. Redeploy the exact reviewed revision and verify health plus a real authenticated request.
4. Record secret-free evidence in the existing incident/PR workflow.

### Database or deployment recovery

Use Neon's supported backup/restore or point-in-time recovery for production. Local restore tooling intentionally refuses non-loopback targets. A Vercel rollback also requires checking compatibility with the current Neon schema; application rollback does not downgrade the database.

See `docs/DATABASE_SAVE_LOAD.md` and `docs/VERCEL_DEPLOYMENT.md`.

## Additional resources

- [OWASP Top Ten](https://owasp.org/www-project-top-ten/)
- [Rust security guidance](https://doc.rust-lang.org/nomicon/)
- [Vercel security](https://vercel.com/docs/security)
- [Neon security](https://neon.tech/docs/introduction/security)
