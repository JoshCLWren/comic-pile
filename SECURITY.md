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
- Production uses environment variables from `.env.production`
- `.env.production` is in `.gitignore` to prevent committing secrets
- Strong secrets must be generated with: `openssl rand -base64 32`

**Best Practices:**
1. Never commit `.env.production` to version control
2. Use different passwords for development and production
3. Rotate secrets regularly
4. Use strong, randomly generated secrets (32+ bytes)

### Image Security

#### Base Image
- Uses official `python:3.13-slim` image
- Slim variants reduce attack surface by excluding unnecessary packages

#### Dependencies
- Minimal system packages installed (`libpq5`, `curl`)
- `apt` cache cleaned after installation
- Multi-stage build reduces final image size

### Network Security

#### Production Architecture
```
Internet → Nginx (port 80/443) → App (port 8000) → PostgreSQL (internal only)
```

**Security Features:**
- Nginx acts as reverse proxy, hiding app details
- PostgreSQL only accessible within Docker network
- App port 8000 not exposed publicly
- SSL/TLS encryption for all traffic

### SSL/TLS Configuration

#### SSL Certificates
- Certificates stored in `./ssl/` directory
- `.gitignore` prevents committing certificates
- Obtain certificates using Certbot: `certbot certonly --standalone -d yourdomain.com`

**Required Files:**
- `./ssl/fullchain.pem` - Certificate chain
- `./ssl/privkey.pem` - Private key

**Nginx Configuration:**
```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:...';
ssl_prefer_server_ciphers off;
```

### Security Headers

Nginx implements security best practice headers:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

**Purpose:**
- **HSTS**: Forces HTTPS connections
- **X-Frame-Options**: Prevents clickjacking
- **X-Content-Type-Options**: Prevents MIME sniffing
- **X-XSS-Protection**: XSS protection
- **Referrer-Policy**: Controls referrer information

### Rate Limiting

API endpoints are rate-limited to prevent abuse:

```nginx
limit_req_zone $binary_remote_addr zone=api:10m;
limit_req zone=api burst=20 nodelay;
```

**Configuration:**
- 10MB shared memory for tracking
- Burst of 20 requests allowed
- Rate limits defined per endpoint

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

**Nginx Container:**
```yaml
healthcheck:
  test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

### Container Hardening Checklist

✅ **Implemented:**
- [x] Non-root user
- [x] Minimal base image (slim)
- [x] Multi-stage build
- [x] Health checks on all containers
- [x] Secrets in environment variables (not code)
- [x] .env.production in .gitignore
- [x] SSL/TLS for all traffic
- [x] Security headers in Nginx
- [x] Rate limiting on API
- [x] No direct database exposure
- [x] Read-only file system where possible

### Vulnerability Scanning

Run vulnerability scans before deployment:

```bash
# Scan Docker image
docker scan comic-pile:latest

# Scan base image
docker scan python:3.13-slim

# Check for exposed secrets
git-secrets --scan

# Check for dependencies with known vulnerabilities
# (Requires setup of tools like Snyk or Dependabot)
```

### Deployment Security Checklist

Before deploying to production:

- [ ] Generate strong secrets with `openssl rand -base64 32`
- [ ] Update `.env.production` with production values
- [ ] Obtain SSL certificates for domain
- [ ] Place certificates in `./ssl/` directory
- [ ] Update `nginx.conf` server_name if needed
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
2. Revoke and regenerate SSL certificates
3. Check audit logs for unauthorized access
4. Update `.env.production` with new secrets
5. Restart containers with new secrets

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
- Monitor SSL certificate expiration
- Regular security audits (quarterly)

### Additional Resources

- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- [OWASP Docker Security](https://owasp.org/www-project-docker-security)
- [Nginx Security Best Practices](https://nginx.org/en/docs/http/ngx_http_core_module.html#variables)
- [Python Security](https://docs.python.org/3/security/index.html)
