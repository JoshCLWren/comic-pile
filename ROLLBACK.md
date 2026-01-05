# Rollback Procedures

This document provides comprehensive rollback procedures for the dockerized PostgreSQL environment. Rollbacks are critical for recovering from failed deployments, bad migrations, data corruption, or other production incidents.

## Table of Contents

1. [Rollback Scenarios](#rollback-scenarios)
2. [Git-Based Rollback](#git-based-rollback)
3. [Database Rollback Procedures](#database-rollback-procedures)
4. [Docker Container Rollback](#docker-container-rollback)
5. [Automated Rollback Scripts](#automated-rollback-scripts)
6. [Testing Rollback Procedures](#testing-rollback-procedures)
7. [Emergency Procedures](#emergency-procedures)

---

## Rollback Scenarios

### Scenario 1: Bad Migration

**Symptoms:**
- Application fails to start after migration
- 500 errors on all endpoints
- Database constraints violated
- Data appears corrupted

**Recovery:**
1. Stop application containers
2. Roll back database to previous migration
3. Verify data integrity
4. Restore application from previous working image
5. Test functionality before marking as recovered

### Scenario 2: Bad Code Deployment

**Symptoms:**
- Application starts but produces incorrect results
- Performance degradation
- UI/UX issues
- API returns wrong data

**Recovery:**
1. Roll back Docker images to previous version
2. Keep database as-is (data is intact)
3. Verify application functions correctly
4. Investigate bad code in separate branch

### Scenario 3: Data Corruption

**Symptoms:**
- Inconsistent query results
- Missing or duplicate records
- Foreign key constraint violations
- Application crashes with database errors

**Recovery:**
1. Stop all application access immediately
2. Create emergency backup of corrupted state
3. Restore from most recent known good backup
4. Validate data integrity
5. Investigate root cause of corruption

### Scenario 4: Database Connection Issues

**Symptoms:**
- "Connection pool exhausted" errors
- Timeouts on database operations
- Intermittent failures

**Recovery:**
1. Check database container health
2. Review connection pool settings
3. Scale database resources if needed
4. Restart application containers

### Scenario 5: Full Deployment Failure

**Symptoms:**
- Docker Compose fails to start
- Multiple services unhealthy
- Complete outage

**Recovery:**
1. Stop all containers
2. Revert docker-compose.yml to previous version
3. Rebuild images from previous code
4. Start services incrementally
5. Monitor health checks

---

## Git-Based Rollback

### Revert Commits (Safe Rollback)

Use when you need to revert changes while keeping git history intact.

```bash
# Revert a specific commit (creates new commit undoing changes)
git revert <commit-hash>

# Revert multiple commits
git revert <commit-hash-1> <commit-hash-2> ... <commit-hash-n>

# Revert range of commits
git revert <oldest-commit>..<newest-commit>

# Example: Revert last 3 commits
git revert HEAD~3..HEAD

# Push reverted changes
git push origin task/rollback-001
```

### Reset Branch (Destructive Rollback)

Use when commits haven't been pushed or you need to completely remove changes.

```bash
# Reset to previous commit (discard uncommitted changes)
git reset --hard HEAD~1

# Reset to specific commit
git reset --hard <commit-hash>

# Keep changes in working directory but reset commit
git reset --soft HEAD~1

# Force push (WARNING: only use on feature branches)
git push origin task/rollback-001 --force
```

### Branch Recovery

```bash
# If you accidentally reset to wrong commit, recover from reflog
git reflog

# Reset to previous state using reflog
git reset --hard HEAD@{2}

# Create branch from specific commit
git checkout -b recovery-branch <commit-hash>
```

### Rollback Deployment to Main

```bash
# 1. Identify last working commit on main
git log --oneline main -10

# 2. Create rollback branch from working commit
git checkout -b hotfix-rollback <working-commit-hash>

# 3. Deploy hotfix branch
git push origin hotfix-rollback

# 4. Update production to use hotfix branch
# (update deployment config or pull hotfix-rollback instead of main)
```

### Best Practices

1. **Never force push to main** - Use `git revert` instead
2. **Tag releases** - Create tags for every deploy: `git tag -a v1.0.0 -m "Release v1.0.0"`
3. **Keep detailed commit messages** - Makes rollback decisions easier
4. **Test rollback locally** - Verify rollback logic before pushing
5. **Communicate with team** - Notify others before rolling back shared branches

---

## Database Rollback Procedures

### PostgreSQL Migration Rollback

Alembic supports rolling back migrations incrementally.

```bash
# Roll back one migration
docker-compose exec app alembic downgrade -1

# Roll back specific number of migrations
docker-compose exec app alembic downgrade -3

# Roll back all migrations to base
docker-compose exec app alembic downgrade base

# Roll back to specific migration
docker-compose exec app alembic downgrade <migration-id>
```

### Restore from Backup

```bash
# 1. Take emergency backup before restoring (in case restore fails)
docker-compose exec db pg_dump -U comicpile comicpile > emergency_backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Stop application containers (prevent writes during restore)
docker-compose stop app

# 3. Restore from backup
docker-compose exec -T db psql -U comicpile -d comicpile < backup_20240101_120000.sql

# 4. Restart application
docker-compose start app

# 5. Verify restore
docker-compose exec app pytest
docker-compose logs -f app  # Check for errors
```

### Point-in-Time Recovery (PITR)

For more advanced recovery scenarios.

```bash
# Requires PostgreSQL WAL archiving to be configured

# 1. Identify point in time to recover to
# (e.g., timestamp or transaction ID)

# 2. Stop database
docker-compose stop db

# 3. Create recovery.conf
cat > /var/lib/postgresql/data/recovery.conf <<EOF
restore_command = 'cp /backups/wal/%f %p'
recovery_target_time = '2024-01-01 12:00:00'
EOF

# 4. Start database (it will recover to target time)
docker-compose start db

# 5. Verify recovery
docker-compose exec db psql -U comicpile -d comicpile -c "SELECT NOW();"
```

### Partial Table Restore

```bash
# Restore specific table from backup
docker-compose exec -T db psql -U comicpile -d comicpile <<EOF
-- Drop existing table (be careful!)
DROP TABLE IF EXISTS users_backup;

-- Rename existing table as backup
ALTER TABLE users RENAME TO users_backup;

-- Restore table from backup file
\i /backups/users_table_backup.sql

-- Verify data
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM users_backup;
EOF
```

### Data Consistency Checks

After any rollback or restore, verify data integrity.

```bash
# Check row counts
docker-compose exec db psql -U comicpile -d comicpile <<EOF
SELECT 'users' as table_name, COUNT(*) as row_count FROM users
UNION ALL
SELECT 'threads', COUNT(*) FROM threads
UNION ALL
SELECT 'sessions', COUNT(*) FROM sessions
UNION ALL
SELECT 'events', COUNT(*) FROM events
UNION ALL
SELECT 'tasks', COUNT(*) FROM tasks;
EOF

# Check foreign key integrity
docker-compose exec db psql -U comicpile -d comicpile <<EOF
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name
FROM
    information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
      AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage AS ccu
      ON ccu.constraint_name = tc.constraint_name
      AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY';
EOF
```

---

## Docker Container Rollback

### Revert Docker Images

```bash
# 1. List all images
docker images | grep comic-pile

# 2. Identify previous working image (look at CREATED column)
# Example: comic-pile latest abc123 2 hours ago
#          comic-pile latest def456 1 day ago  <- Use this one

# 3. Tag previous image as current
docker tag <previous-image-id> comic-pile:latest

# 4. Restart containers with new tag
docker-compose down
docker-compose up -d

# 5. Verify containers started correctly
docker-compose ps
docker-compose logs -f app
```

### Revert docker-compose.yml

```bash
# 1. Checkout previous version of docker-compose.yml
git checkout HEAD~1 docker-compose.yml

# 2. Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 3. Monitor logs for issues
docker-compose logs -f
```

### Rollback Container Configuration

```bash
# 1. Stop containers
docker-compose stop

# 2. Remove containers (keeps volumes and data)
docker-compose rm -f

# 3. Start with previous configuration
docker-compose up -d

# 4. Verify health
docker-compose ps
curl http://localhost:8000/health
```

### Volume Rollback

```bash
# WARNING: This destroys data. Only use as last resort.

# 1. Stop containers
docker-compose down

# 2. Remove volumes
docker-compose down -v

# 3. Start fresh (will recreate volumes)
docker-compose up -d

# 4. Restore from backup if needed
# See "Restore from Backup" section above
```

### Rolling Deployment Rollback

For production environments using rolling updates.

```bash
# If using health checks and rolling restart:

# 1. Check previous healthy containers
docker ps -a --filter "name=comic-pile-app"

# 2. Stop new containers
docker stop <new-container-id>

# 3. Restart previous containers
docker start <previous-container-id>

# 4. Remove failed new containers
docker rm <new-container-id>

# 5. Verify service is healthy
curl http://localhost:8000/health
```

---

## Automated Rollback Scripts

### Full Rollback Script

Create `scripts/rollback.sh`:

```bash
#!/bin/bash
set -e

# Full rollback script for dockerized PostgreSQL environment
# Usage: ./scripts/rollback.sh <rollback-type> [options]

ROLLBACK_TYPE="${1:-help}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups"
mkdir -p "$BACKUP_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function: Database rollback
rollback_database() {
    log_info "Starting database rollback..."

    # Take emergency backup
    log_info "Creating emergency backup..."
    docker-compose exec -T db pg_dump -U comicpile comicpile > "$BACKUP_DIR/emergency_before_rollback_$TIMESTAMP.sql"

    # Roll back migrations
    log_info "Rolling back migrations..."
    docker-compose exec app alembic downgrade base

    log_info "Database rollback complete"
    log_info "Emergency backup: $BACKUP_DIR/emergency_before_rollback_$TIMESTAMP.sql"
}

# Function: Git rollback
rollback_git() {
    local COMMIT_HASH="${2:-HEAD~1}"

    log_info "Rolling back git to $COMMIT_HASH..."

    # Create backup branch
    log_info "Creating backup branch..."
    git branch "pre-rollback-backup-$TIMESTAMP"

    # Reset to previous commit
    git reset --hard "$COMMIT_HASH"

    log_info "Git rollback complete"
    log_info "Backup branch: pre-rollback-backup-$TIMESTAMP"
}

# Function: Docker image rollback
rollback_docker() {
    local IMAGE_ID="${2}"

    log_info "Rolling back Docker image..."

    if [ -z "$IMAGE_ID" ]; then
        log_error "Please provide image ID: ./scripts/rollback.sh docker <image-id>"
        exit 1
    fi

    # Stop containers
    log_info "Stopping containers..."
    docker-compose down

    # Tag previous image as latest
    log_info "Retagging previous image..."
    docker tag "$IMAGE_ID" comic-pile:latest

    # Restart containers
    log_info "Restarting containers..."
    docker-compose up -d

    # Wait for health check
    log_info "Waiting for health check..."
    sleep 10

    # Verify health
    if curl -f http://localhost:8000/health; then
        log_info "Docker rollback successful"
    else
        log_error "Health check failed after rollback"
        exit 1
    fi
}

# Function: Full system rollback (git + docker + db)
rollback_full() {
    log_warn "This will rollback git, rebuild Docker images, and reset database"
    read -p "Are you sure? (yes/no): " CONFIRM

    if [ "$CONFIRM" != "yes" ]; then
        log_info "Rollback cancelled"
        exit 0
    fi

    log_info "Starting full system rollback..."

    # 1. Git rollback
    log_info "Step 1: Rolling back git..."
    rollback_git "${2:-HEAD~1}"

    # 2. Rebuild Docker images
    log_info "Step 2: Rebuilding Docker images..."
    docker-compose build --no-cache

    # 3. Stop containers
    log_info "Step 3: Stopping containers..."
    docker-compose down

    # 4. Database rollback
    log_info "Step 4: Rolling back database..."
    rollback_database

    # 5. Restart services
    log_info "Step 5: Restarting services..."
    docker-compose up -d

    # 6. Verify health
    log_info "Step 6: Verifying health..."
    sleep 15

    if curl -f http://localhost:8000/health; then
        log_info "Full rollback successful"
    else
        log_error "Health check failed after rollback"
        log_error "Check logs: docker-compose logs"
        exit 1
    fi
}

# Function: Restore from backup
restore_backup() {
    local BACKUP_FILE="${2}"

    if [ -z "$BACKUP_FILE" ]; then
        log_error "Please provide backup file: ./scripts/rollback.sh restore <backup-file>"
        exit 1
    fi

    if [ ! -f "$BACKUP_FILE" ]; then
        log_error "Backup file not found: $BACKUP_FILE"
        exit 1
    fi

    log_info "Restoring from $BACKUP_FILE..."

    # Stop application
    log_info "Stopping application..."
    docker-compose stop app

    # Restore database
    log_info "Restoring database..."
    docker-compose exec -T db psql -U comicpile -d comicpile < "$BACKUP_FILE"

    # Start application
    log_info "Starting application..."
    docker-compose start app

    log_info "Restore complete"
}

# Help function
show_help() {
    cat << EOF
Rollback Script for Dockerized PostgreSQL Environment

Usage: ./scripts/rollback.sh <command> [options]

Commands:
    database           Rollback all database migrations to base
    git [commit]       Rollback git to previous commit (default: HEAD~1)
    docker <image-id>  Rollback to previous Docker image
    full [commit]      Full rollback (git + docker + database)
    restore <backup>   Restore database from backup file
    help               Show this help message

Examples:
    ./scripts/rollback.sh database
    ./scripts/rollback.sh git HEAD~2
    ./scripts/rollback.sh docker abc123def456
    ./scripts/rollback.sh full HEAD~1
    ./scripts/rollback.sh restore ./backups/backup_20240101_120000.sql

EOF
}

# Main dispatch
case "$ROLLBACK_TYPE" in
    database)
        rollback_database
        ;;
    git)
        rollback_git "$2"
        ;;
    docker)
        rollback_docker "$2"
        ;;
    full)
        rollback_full "$2"
        ;;
    restore)
        restore_backup "$2"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $ROLLBACK_TYPE"
        show_help
        exit 1
        ;;
esac
```

Make the script executable:

```bash
chmod +x scripts/rollback.sh
```

### Quick Rollback Alias

Add to your `.bashrc` or `.zshrc`:

```bash
# Quick rollback alias
alias rollback='docker-compose exec app alembic downgrade -1'

# Full rollback alias
alias rollback-full='docker-compose exec app alembic downgrade base && docker-compose restart app'
```

---

## Testing Rollback Procedures

### Test Database Rollback

```bash
# 1. Create a test migration
docker-compose exec app alembic revision -m "test_rollback"

# 2. Apply migration
docker-compose exec app alembic upgrade head

# 3. Verify migration applied
docker-compose exec db psql -U comicpile -d comicpile -c "SELECT * FROM alembic_version;"

# 4. Rollback migration
docker-compose exec app alembic downgrade -1

# 5. Verify rollback
docker-compose exec db psql -U comicpile -d comicpile -d comicpile -c "SELECT * FROM alembic_version;"

# 6. Clean up test migration
# (delete migration file manually if not needed)
```

### Test Docker Image Rollback

```bash
# 1. Build current image
docker-compose build

# 2. Tag current image as "working"
docker images | grep comic-pile
docker tag <current-image-id> comic-pile:working

# 3. Make a change and rebuild
# (modify code, then:)
docker-compose build --no-cache

# 4. Test new image
docker-compose up -d
docker-compose ps

# 5. Rollback to working image
docker tag <working-image-id> comic-pile:latest
docker-compose up -d

# 6. Verify rollback worked
docker-compose ps
docker-compose logs app
```

### Test Full Rollback Scenario

```bash
# 1. Create baseline
docker-compose up -d
docker-compose exec app pytest

# 2. Make intentional breaking change
# (e.g., modify app/main.py to add syntax error)

# 3. Deploy broken change
docker-compose build
docker-compose up -d

# 4. Verify broken state (should see errors)
docker-compose logs app

# 5. Rollback
docker-compose down
git checkout HEAD~1 .
docker-compose build --no-cache
docker-compose up -d

# 6. Verify recovery
docker-compose exec app pytest
curl http://localhost:8000/health
```

### Test Backup and Restore

```bash
# 1. Create test data
docker-compose exec app python -m scripts.seed_data

# 2. Create backup
docker-compose exec -T db pg_dump -U comicpile comicpile > test_backup.sql

# 3. Modify data
docker-compose exec db psql -U comicpile -d comicpile -c "DELETE FROM users;"

# 4. Verify data deleted
docker-compose exec db psql -U comicpile -d comicpile -c "SELECT COUNT(*) FROM users;"

# 5. Restore backup
docker-compose exec -T db psql -U comicpile -d comicpile < test_backup.sql

# 6. Verify data restored
docker-compose exec db psql -U comicpile -d comicpile -c "SELECT COUNT(*) FROM users;"
```

### Verification Checklist

After any rollback, verify:

- [ ] All containers running (`docker-compose ps`)
- [ ] Health checks passing (`curl http://localhost:8000/health`)
- [ ] Database migrations at expected version (`alembic current`)
- [ ] Application logs show no errors (`docker-compose logs app`)
- [ ] API endpoints responding correctly
- [ ] Tests passing (`pytest`)
- [ ] Data integrity checks passing
- [ ] No foreign key constraint violations

---

## Emergency Procedures

### Emergency Shutdown

If you need to stop everything immediately:

```bash
# Stop all containers immediately
docker-compose down

# Or stop without removing (keeps containers for investigation)
docker-compose stop

# View what was running before stopping
docker-compose ps -a
```

### Emergency Backup Before Rollback

Always backup before rolling back, even if the system appears broken:

```bash
# Quick database backup
docker-compose exec -T db pg_dump -U comicpile comicpile > emergency_$(date +%Y%m%d_%H%M%S).sql

# Quick git backup
git branch emergency-backup-$(date +%Y%m%d_%H%M%S)

# Quick docker image backup
docker save comic-pile:latest > comic-pile-emergency-$(date +%Y%m%d_%H%M%S).tar
```

### Emergency Rollback Command

One-command rollback to last known good state:

```bash
# Stop everything, reset git, rebuild, restore database
docker-compose down \
  && git reset --hard HEAD~1 \
  && docker-compose build --no-cache \
  && docker-compose up -d \
  && docker-compose exec app alembic downgrade base \
  && docker-compose restart app
```

### Contact Information

For emergencies requiring human intervention:

- On-call engineer: [PHONE/SLACK]
- Database administrator: [PHONE/SLACK]
- DevOps team: [PHONE/SLACK]

### Incident Report Template

After any emergency rollback, file an incident report:

```markdown
# Incident Report: [Brief Title]

Date: [Date/time]
Severity: [Critical/High/Medium/Low]
Reporter: [Name]

## Summary
[What happened]

## Impact
[Who was affected, what services were down]

## Timeline
- [Time]: Event occurred
- [Time]: Detected
- [Time]: Rollback initiated
- [Time]: Service restored

## Root Cause
[Why it happened]

## Resolution
[How it was fixed]

## Follow-up Actions
- [ ] [Action 1]
- [ ] [Action 2]
- [ ] [Action 3]

## Lessons Learned
[What can we do better next time]
```

---

## Best Practices

1. **Always backup before rolling back**
2. **Test rollback procedures in staging**
3. **Document rollback decisions in changelog**
4. **Use tags for release points**
5. **Monitor rollback health closely**
6. **Communicate with stakeholders during rollback**
7. **Perform post-mortem after major rollbacks**
8. **Automate rollback scripts for common scenarios**
9. **Keep rollback procedures updated with code changes**
10. **Practice rollback drills quarterly**

---

## Related Documentation

- [DOCKER_MIGRATION.md](./DOCKER_MIGRATION.md) - Docker and migration guide
- [BACKUP_PROCEDURES.md](./BACKUP_PROCEDURES.md) - Backup procedures (if exists)
- [INCIDENT_RESPONSE.md](./INCIDENT_RESPONSE.md) - Incident response plan (if exists)
