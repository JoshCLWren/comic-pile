# Security Documentation

## Runtime Security Architecture

The application runtime is a static React/Vite frontend and a single native Rust
API function (`api/native_roll.rs`) deployed on Vercel, with PostgreSQL hosted by
Neon. The retired Python/FastAPI application no longer exists; guidance that
references it is historical.

```
Internet → Vercel edge (TLS termination) → static frontend + native Rust API function → Neon PostgreSQL
```

**Security Features:**
- TLS termination handled by the Vercel platform
- Security headers applied at the Vercel ingress on the static frontend routes
  (generated `vercel.json` route `headers`; do not hand-edit that file)
- Authentication rate limiting, durable login lockout, and outbound-provider
  backoff enforced inside the native Rust service (see [docs/rate_limiting.md](docs/rate_limiting.md))
- Database reachable only through the configured Neon connection URL;
  production startup rejects a database URL without `sslmode=require`

### SSL/TLS Configuration

TLS certificates are provisioned and renewed automatically by the Vercel platform;
no certificate files are stored in this repository. Frontend responses declare HSTS
via the ingress headers
(`max-age=63072000; includeSubDomains; preload`). Production database connections
require `sslmode=require`.

### Security Headers

The generated `vercel.json` applies these headers to the static frontend routes
(`/`, SPA fallback, and fingerprinted assets get cache rules; HTML routes get the
full set):

```http
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: https:; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https://fonts.googleapis.com; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; frame-src 'none';
Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

**Purpose:**
- **CSP**: Restricts resource loading origins
- **HSTS**: Forces HTTPS connections
- **X-Frame-Options**: Prevents clickjacking
- **X-Content-Type-Options**: Prevents MIME sniffing
- **X-XSS-Protection**: XSS protection
- **Referrer-Policy**: Controls referrer information
- **Permissions-Policy**: Disables sensitive browser capabilities

Recorded gap: the native Rust API responses do not currently emit this header set
themselves; the ingress-level headers above cover the static frontend routes. Treat
API-response security headers as an open runtime work item, not an implemented
control.

### Authentication and Abuse Controls

- Browser clients authenticate with a bearer access token, an HttpOnly refresh
  cookie, and a double-submit CSRF cookie/header on state-changing requests
  (see [docs/API.md](docs/API.md#authentication-and-csrf)).
- Authentication endpoints use a process-local rate limiter keyed by client IP or
  token digest, with a bounded key map; failed logins are additionally locked out
  durably in PostgreSQL and survive restarts
  (see [docs/rate_limiting.md](docs/rate_limiting.md)).
- Outbound bug-report filing and ComicVine provider calls apply their own rate
  limits and backoff with `429` + `Retry-After` behavior.

### Secrets Management

#### Development Environment
- `docker-compose.yml` contains hardcoded development passwords (acceptable for local development only)
- `comicpile_password` and `pgadmin_password` are placeholder credentials

#### Production Environment
- Production runs on Vercel + Neon; secrets are configured as Vercel project environment variables and GitHub Actions secrets
- `.env.production` remains in `.gitignore` to prevent committing secrets locally
- Strong secrets must be generated with: `openssl rand -base64 32`

**Best Practices:**
1. Never commit `.env.production` to version control
2. Use different passwords for development and production
3. Rotate secrets regularly
4. Use strong, randomly generated secrets (32+ bytes)

### Container Security

Comic Pile does not ship a production application container. Docker is used for:

- Local PostgreSQL (`docker-compose.yml`, `postgres:16-alpine`, placeholder
  development credentials) and optional pgAdmin.
- The same-origin test topology (`docker-compose.test.yml`).
- The CI tooling image (`Dockerfile.ci`), which packages Python/Node/Playwright
  tooling for GitHub Actions jobs — it is not a production runtime.

Keep production credentials out of all Compose files; they are for local and test
databases only.

### Health Checks

- The native service exposes dependency-free liveness at `GET /api/v2/health`
  (local standalone also at `GET /health`); it opens no database connection
  (see [docs/OPERATIONAL_HEALTH.md](docs/OPERATIONAL_HEALTH.md)).
- The local database container declares a `pg_isready` healthcheck in
  `docker-compose.yml`.

### Security Checklist

✅ **Implemented:**
- [x] Secrets in environment variables (not code)
- [x] `.env.production` in `.gitignore`
- [x] TLS terminated by the Vercel platform
- [x] Security headers on static frontend routes at the Vercel ingress
- [x] Authentication rate limiting and durable login lockout
- [x] Production database connections require `sslmode=require`
- [x] Dependency-free liveness endpoint with no infrastructure detail
- [x] No direct database exposure

⚠️ **Known gaps (recorded, not implemented):**
- [ ] Security headers on native Rust API responses (ingress covers the static routes)
- [ ] Automated secret scanning in CI

### Vulnerability Scanning

Run vulnerability scans before deployment:

```bash
# Scan the CI tooling image
docker scout cves comic-pile-ci:latest

# Check for exposed secrets
git-secrets --scan

# Check for dependencies with known vulnerabilities
# (Requires setup of tools like Snyk or Dependabot)
```

### Deployment Security Checklist

Before deploying to production:

- [ ] Generate strong secrets with `openssl rand -base64 32`
- [ ] Update Vercel project environment variables with production values
- [ ] Run vulnerability scans (CI image and dependencies)
- [ ] Test health checks locally (`GET /api/v2/health`)
- [ ] Verify no secrets in git history
- [ ] Review .gitignore includes all sensitive files
- [ ] Backup database before migration
- [ ] Test rollback procedure

### Incident Response

#### Compromised Secrets
If secrets are leaked:
1. Immediately rotate all secrets
2. Rotate the affected Vercel project environment variables and GitHub Actions secrets
3. Check audit logs for unauthorized access
4. Redeploy so services pick up the new secrets

#### Container Breach
If a local/CI container is compromised:
1. Stop affected containers immediately
2. Review container logs for indicators of compromise
3. Rotate all secrets that were reachable from the container
4. Update to latest base images with security patches
5. Rebuild and rerun

### Monitoring Recommendations

- Monitor service logs for suspicious activity
- Set up alerts for health check failures
- Track rate limit violations and login lockouts
- Regular security audits (quarterly)

### Additional Resources

- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- [OWASP Docker Security](https://owasp.org/www-project-docker-security)
- [Python Security](https://docs.python.org/3/security/index.html)
