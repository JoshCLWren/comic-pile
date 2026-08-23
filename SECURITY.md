# Security Documentation

## Docker Security Configuration

### Non-Root User
The application runs as a non-root user (`appuser`) for security:

```dockerfile
RUN useradd --create-home --shell /bin/bash appuser
USER appuser
```

**Benefits:**
- If container is compromised, attacker has limited privileges
- Prevents privilege escalation attacks
- Follows security best practices

### Secrets Management

#### Development Environment
- `docker-compose.yml` contains hardcoded development passwords (acceptable for local development only)
- `postgres_password` and `pgadmin_password` are placeholder credentials

#### Production Environment
- Production runs on Vercel + Neon; secrets are configured as Vercel project environment variables and GitHub Actions secrets
- `.env.production` remains in `.gitignore` to prevent committing secrets locally
- Strong secrets must be generated with: `openssl rand -base64 32`

**Best Practices:**
1. Never commit `.env.production` to version control
2. Use different passwords for development and production
3. Rotate secrets regularly
4. Use strong, randomly generated secrets (32+ bytes)

### Image Security

#### Base Image
- Uses official `python:3.14-slim` image
- Slim variants reduce attack surface by excluding unnecessary packages

#### Dependencies
- Minimal system packages installed (`libpq5`, `curl`)
- `apt` cache cleaned after installation
- Multi-stage build reduces final image size

### Network Security

#### Production Architecture
```
Internet → Vercel edge (TLS termination) → FastAPI API function → Neon PostgreSQL
```

**Security Features:**
- TLS termination handled by the Vercel platform
- Security headers applied by application middleware (`app/middleware/security_headers.py`)
- Rate limiting enforced at the application layer (`app/middleware/rate_limit.py`)
- Database reachable only through the configured Neon connection URL

### SSL/TLS Configuration

TLS certificates are provisioned and renewed automatically by the Vercel platform;
no certificate files are stored in this repository. Application responses also declare
HSTS via `SecurityHeadersMiddleware`
(`max-age=63072000; includeSubDomains; preload` in production environments).

### Security Headers

The FastAPI application sets security headers through `SecurityHeadersMiddleware`
(`app/middleware/security_headers.py`):

```http
Content-Security-Policy: default-src 'self'; ...
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

### Rate Limiting

API endpoints are rate-limited in the application using slowapi
(`app/middleware/rate_limit.py`, registered in `app/main.py`):

**Configuration:**
- Limits are applied per endpoint via the shared limiter
- Requests are keyed by client IP address
- Rate limiting responses return HTTP 429

### Health Checks

All services have health checks:

**App Container:**
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

**Database Container:**
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U comicpile"]
  interval: 10s
  timeout: 5s
  retries: 5
```

### Container Hardening Checklist

✅ **Implemented:**
- [x] Non-root user
- [x] Minimal base image (slim)
- [x] Multi-stage build
- [x] Health checks on containers
- [x] Secrets in environment variables (not code)
- [x] .env.production in .gitignore
- [x] TLS terminated by the Vercel platform
- [x] Security headers in application middleware
- [x] Rate limiting on API (slowapi)
- [x] No direct database exposure
- [x] Read-only file system where possible

### Vulnerability Scanning

Run vulnerability scans before deployment:

```bash
# Scan Docker image
docker scout cves comic-pile:latest

# Scan base image
docker scout cves python:3.14-slim

# Check for exposed secrets
git-secrets --scan

# Check for dependencies with known vulnerabilities
# (Requires setup of tools like Snyk or Dependabot)
```

### Deployment Security Checklist

Before deploying to production:

- [ ] Generate strong secrets with `openssl rand -base64 32`
- [ ] Update Vercel project environment variables with production values
- [ ] Run vulnerability scan on Docker image
- [ ] Test health checks locally
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
If container is compromised:
1. Stop affected containers immediately
2. Review container logs for indicators of compromise
3. Rotate all secrets
4. Update to latest base images with security patches
5. Rebuild and redeploy containers

### Monitoring Recommendations

- Monitor container logs for suspicious activity
- Set up alerts for health check failures
- Track rate limit violations
- Regular security audits (quarterly)

### Additional Resources

- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- [OWASP Docker Security](https://owasp.org/www-project-docker-security)
- [Python Security](https://docs.python.org/3/security/index.html)
