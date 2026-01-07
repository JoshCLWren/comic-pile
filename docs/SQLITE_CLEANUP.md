# SQLite Cleanup After PostgreSQL Migration

This guide covers the safe removal of SQLite database files after a successful PostgreSQL migration.

## ⚠️ Important Warnings

**READ THIS ENTIRE DOCUMENT BEFORE PROCEEDING**

- **SQLite cleanup is irreversible** - Once deleted, you cannot recover data without a backup
- **Verify PostgreSQL migration thoroughly** before removing SQLite files
- **Keep SQLite backup for at least 1 week** after migration to allow rollback time
- **Test application thoroughly** with PostgreSQL before cleanup

## Prerequisites

Before cleaning up SQLite files, ensure you have completed:

1. ✅ **PG-MIGRATE-001**: Created .env file with PostgreSQL DATABASE_URL
2. ✅ **PG-MIGRATE-002**: Ran PostgreSQL data migration with verification
3. ✅ **PG-MIGRATE-003**: Updated test configuration for PostgreSQL
4. ✅ **PG-MIGRATE-004**: Updated documentation for PostgreSQL
5. ✅ **PG-MIGRATE-005**: Created and ran migration verification tests

## Step 1: Verify PostgreSQL Migration Success

Before removing any SQLite files, verify that PostgreSQL has all your data correctly.

### 1.1 Run Migration Verification Tests

```bash
# Run migration integrity tests
pytest tests/test_migration_verification.py -v
```

Expected output: All tests pass, no errors.

### 1.2 Compare Row Counts

```bash
# Connect to SQLite and count rows
sqlite3 comic_pile.db "SELECT COUNT(*) FROM users;"
sqlite3 comic_pile.db "SELECT COUNT(*) FROM threads;"
sqlite3 comic_pile.db "SELECT COUNT(*) FROM sessions;"
sqlite3 comic_pile.db "SELECT COUNT(*) FROM events;"
sqlite3 comic_pile.db "SELECT COUNT(*) FROM tasks;"
sqlite3 comic_pile.db "SELECT COUNT(*) FROM settings;"

# Connect to PostgreSQL and count rows
psql $DATABASE_URL -c "SELECT COUNT(*) FROM users;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM threads;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sessions;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM events;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM tasks;"
psql $DATABASE_URL -c "SELECT COUNT(*) FROM settings;"
```

**All row counts must match exactly.**

### 1.3 Verify Foreign Key Relationships

```bash
# Run a quick integrity check on PostgreSQL
python -c "
from app.database import SessionLocal
from app.models import Thread, Session, Event, Task

db = SessionLocal()

# Check threads have users
threads_without_users = db.query(Thread).filter(Thread.user_id.is_(None)).count()
print(f'Threads without users: {threads_without_users}')

# Check sessions have users
sessions_without_users = db.query(Session).filter(Session.user_id.is_(None)).count()
print(f'Sessions without users: {sessions_without_users}')

# Check events have sessions
events_without_sessions = db.query(Event).filter(Event.session_id.is_(None)).count()
print(f'Events without sessions: {events_without_sessions}')

# Check events have threads
events_without_threads = db.query(Event).filter(Event.thread_id.is_(None)).count()
print(f'Events without threads: {events_without_threads}')

db.close()

if threads_without_users == 0 and sessions_without_users == 0 and events_without_sessions == 0 and events_without_threads == 0:
    print('✅ Foreign key relationships verified')
else:
    print('❌ Foreign key issues found')
"
```

All counts should be 0.

### 1.4 Test Application with PostgreSQL

```bash
# Start the application with PostgreSQL
make dev

# Open http://localhost:8000 and verify:
# - You can see your threads
# - You can roll dice
# - You can rate comics
# - Session history is visible
# - Queue management works

# Run API tests
pytest tests/ -v

# Run browser tests (if available)
pytest tests_e2e/ -v
```

Everything should work exactly as it did with SQLite.

## Step 2: Create SQLite Backup

Before removing SQLite files, create a backup as a safety measure.

### 2.1 Export SQLite to JSON

```bash
# Export current SQLite database to JSON
python -m scripts.export_db

# Rename export with timestamp
mv db_export.json db_export_sqlite_pre_cleanup_$(date +%Y%m%d_%H%M%S).json

# Verify export file exists and has data
ls -lh db_export_sqlite_pre_cleanup_*.json
```

### 2.2 Create SQLite Database Backup

```bash
# Create a compressed backup of the SQLite database
tar -czf comic_pile.db.backup.$(date +%Y%m%d_%H%M%S).tar.gz comic_pile.db

# Verify backup exists
ls -lh comic_pile.db.backup.*.tar.gz
```

### 2.3 Store Backup Securely

```bash
# Move backups to a safe location (outside project directory if possible)
mkdir -p ~/comic-pile-backups
mv db_export_sqlite_pre_cleanup_*.json ~/comic-pile-backups/
mv comic_pile.db.backup.*.tar.gz ~/comic-pile-backups/

# Verify backups are safe
ls -lh ~/comic-pile-backups/
```

**Keep these backups for at least 1 week** before deleting them.

## Step 3: Remove SQLite Files

After verifying PostgreSQL migration and creating backups, you can safely remove SQLite files.

### 3.1 Identify All SQLite Files

```bash
# Find all SQLite database files
find . -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" | grep -v ".venv"
```

Typical output:
```
./comic_pile.db
```

### 3.2 Verify Files to Delete

Review the list from step 3.1. **Do not delete files you're not sure about**.

### 3.3 Remove SQLite Files

```bash
# Remove main SQLite database
rm comic_pile.db

# Remove any SQLite journal files (if they exist)
rm -f comic_pile.db-journal
rm -f comic_pile.db-wal
rm -f comic_pile.db-shm

# Verify files are removed
ls -lh *.db *.sqlite* 2>&1
```

Expected output: No such file or directory (files are gone).

### 3.4 Remove SQLite-Related Environment Variables (Optional)

If you have SQLite-specific environment variables in your `.env` file, you can remove them:

```bash
# Edit .env file
nano .env

# Remove or comment out these lines:
# SQLITE_DB_PATH=comic_pile.db
# DATABASE_URL=sqlite:///./comic_pile.db

# Save and exit
```

## Step 4: Verify Application Still Works

After cleanup, verify the application works correctly with PostgreSQL only.

### 4.1 Start Application

```bash
# Start the dev server
make dev
```

### 4.2 Run Health Check

```bash
# Check health endpoint
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","database":"connected"}
```

### 4.3 Run All Tests

```bash
# Run full test suite
pytest tests/ -v

# Run coverage
pytest --cov=comic_pile --cov-report=term-missing

# Expected: All tests pass, coverage >= 96%
```

### 4.4 Manual Verification

Open http://localhost:8000 and verify:
- Application loads without errors
- All your data is visible
- All features work (roll, rate, queue, history)
- No error messages in logs

## Rollback Procedures

If you discover issues after cleanup, use these rollback procedures.

### Scenario 1: Need to Restore from SQLite Backup

You have JSON and tar.gz backups from Step 2.

```bash
# Copy backup back to project directory
cp ~/comic-pile-backups/comic_pile.db.backup.*.tar.gz .
tar -xzf comic_pile.db.backup.*.tar.gz

# Update DATABASE_URL to use SQLite
nano .env

# Change DATABASE_URL to:
# DATABASE_URL=sqlite:///./comic_pile.db

# Restart application
make dev

# Import JSON backup if needed
cp ~/comic-pile-backups/db_export_sqlite_pre_cleanup_*.json db_export.json
python -m scripts.import_db
```

### Scenario 2: Need to Re-migrate from SQLite

You didn't delete SQLite, but PostgreSQL has issues.

```bash
# Reset PostgreSQL database
psql $DATABASE_URL -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Run Alembic migrations to recreate schema
make migrate

# Run migration script again
python scripts/migrate_sqlite_to_postgres.py

# Verify migration (see Step 1)
```

### Scenario 3: Need to Switch Back to SQLite Completely

PostgreSQL has issues and you want to abandon migration.

```bash
# Restore SQLite database
cp ~/comic-pile-backups/comic_pile.db.backup.*.tar.gz .
tar -xzf comic_pile.db.backup.*.tar.gz

# Update .env to use SQLite
nano .env

# Set DATABASE_URL:
# DATABASE_URL=sqlite:///./comic_pile.db

# Remove PostgreSQL connection settings if desired
# (keep them if you might try migration again later)

# Restart application
make dev

# Verify everything works
pytest tests/ -v
```

### Scenario 4: Need to Restore from JSON Backup

Both SQLite and PostgreSQL are corrupted, but you have JSON backup.

```bash
# Decide which database to use (PostgreSQL recommended)

# For PostgreSQL:
# Ensure DATABASE_URL points to PostgreSQL in .env
python -m scripts.import_db

# For SQLite:
# Set DATABASE_URL=sqlite:///./comic_pile.db in .env
python -m scripts.import_db

# Verify data
pytest tests/test_migration_verification.py -v
```

## Cleanup Timeline

Recommended timeline for safe cleanup:

| Day | Action | Notes |
|-----|--------|-------|
| Day 0 | Run migration verification | Ensure PostgreSQL has all data |
| Day 0 | Create SQLite backups | Keep for 1 week minimum |
| Day 0 | Remove SQLite files | Test application immediately |
| Days 1-7 | Monitor application | Use all features, watch for bugs |
| Day 7+ | Delete SQLite backups | Only if no issues found |

## Common Issues and Solutions

### Issue: Application Won't Start After Cleanup

**Symptom**: Error about missing database file.

**Cause**: DATABASE_URL still points to SQLite.

**Solution**:
```bash
# Check .env file
cat .env | grep DATABASE_URL

# Should be:
# DATABASE_URL=postgresql+psycopg://user:password@host:port/database

# Not:
# DATABASE_URL=sqlite:///./comic_pile.db
```

### Issue: Tests Fail After Cleanup

**Symptom**: Tests looking for SQLite database.

**Cause**: Test fixtures still using SQLite.

**Solution**:
```bash
# Update tests/conftest.py to use PostgreSQL
# See PG-MIGRATE-003 for details

# Run tests again
pytest tests/ -v
```

### Issue: Data Missing in PostgreSQL

**Symptom**: Some data didn't migrate correctly.

**Cause**: Migration script failed or incomplete.

**Solution**:
```bash
# Restore SQLite backup
cp ~/comic-pile-backups/comic_pile.db.backup.*.tar.gz .
tar -xzf comic_pile.db.backup.*.tar.gz

# Investigate migration script logs
# Check migration script output for errors

# Re-run migration after fixing issues
python scripts/migrate_sqlite_to_postgres.py
```

### Issue: Foreign Key Violations in PostgreSQL

**Symptom**: Errors about constraint violations.

**Cause**: Data migrated in wrong order or missing relationships.

**Solution**:
```bash
# Restore SQLite backup
cp ~/comic-pile-backups/comic_pile.db.backup.*.tar.gz .
tar -xzf comic_pile.db.backup.*.tar.gz

# Reset PostgreSQL
psql $DATABASE_URL -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# Recreate schema
make migrate

# Re-migrate (ensure all tables migrate in correct order)
python scripts/migrate_sqlite_to_postgres.py
```

## Verification Checklist

Before considering cleanup complete, verify:

- [ ] Migration verification tests pass
- [ ] Row counts match between SQLite and PostgreSQL
- [ ] Foreign key relationships are intact
- [ ] Application starts without errors
- [ ] All features work (roll, rate, queue, history)
- [ ] All tests pass (pytest)
- [ ] Coverage meets requirements (>= 96%)
- [ ] Manual testing shows no issues
- [ ] SQLite backups are stored securely
- [ ] Application has been used for at least 1 day with PostgreSQL

## Related Documentation

- [DATABASE_SAVE_LOAD.md](./DATABASE_SAVE_LOAD.md) - Backup and restore procedures
- [scripts/migrate_sqlite_to_postgres.py](../scripts/migrate_sqlite_to_postgres.py) - Migration script
- [AGENTS.md](../AGENTS.md) - Project guidelines and PostgreSQL setup
- [README.md](../README.md) - Quick start and tech stack

## Summary

**SQLite cleanup is safe when:**
1. PostgreSQL migration is fully verified
2. All tests pass with PostgreSQL
3. Application works correctly with PostgreSQL
4. SQLite backups are stored for rollback
5. No issues found after at least 1 day of use

**Never skip verification steps.** The time spent verifying PostgreSQL migration is far less than the time spent recovering from a failed cleanup.

**When in doubt, keep the SQLite backup longer.** Better to have an unused backup than to need one and not have it.
