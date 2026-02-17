# Database Save/Load Guide

Save your database to JSON file for backup, or restore from JSON to load previous state.

## PostgreSQL Native Backups (Recommended)

The project supports PostgreSQL native backups using `pg_dump` for complete database backups including schema, data, indexes, and constraints.

### Quick Start

```bash
# Create PostgreSQL backup
make backup-postgres

# List all PostgreSQL backups
make list-postgres-backups

# Restore from specific backup
make restore-postgres FILE=backups/postgres/postgres_backup_comicpile_20240104_120530.sql.gz
```

### Backup Script Details

The `scripts/backup_postgres.sh` script:

1. Parses `DATABASE_URL` from `.env` file
2. Creates timestamped compressed SQL backups using `pg_dump`
3. Stores backups in `backups/postgres/` directory
4. Implements automatic rotation (keeps last 10 backups by default)
5. Verifies backup integrity with `gzip -t`

### Restore Script Details

The `scripts/restore_postgres.sh` script:

1. Parses `DATABASE_URL` from `.env` file
2. Lists available backups when run without arguments
3. Verifies backup file integrity with `gzip -t`
4. Prompts for confirmation before restoring
5. Restores database using `gunzip` and `psql`
6. Verifies database contents after restore

### Backup Configuration

Environment variables in `.env`:

```bash
BACKUP_DIR=backups          # Base backup directory (PostgreSQL uses backups/postgres/)
MAX_BACKUPS=10             # Maximum number of backups to keep
```

### Backup File Format

Backups are named: `postgres_backup_{database}_{timestamp}.sql.gz`

Example: `postgres_backup_comicpile_20240104_143022.sql.gz`

### Manual PostgreSQL Restore Procedure

To restore from a PostgreSQL backup:

**Step 1: List available backups**

```bash
make list-postgres-backups
```

Output:
```
Available PostgreSQL backups:
-rw-r--r-- 1 josh josh 1.2M Jan  4 10:31 backups/postgres/postgres_backup_comicpile_20260104_103111.sql.gz
-rw-r--r-- 1 josh josh 1.2M Jan  4 10:35 backups/postgres/postgres_backup_comicpile_20260104_103354.sql.gz
```

**Step 2: Select the backup to restore**

Choose the backup with the appropriate timestamp.

**Step 3: Restore using make target**

```bash
make restore-postgres FILE=backups/postgres/postgres_backup_comicpile_20240104_103354.sql.gz
```

**Step 4: Restore using script directly**

```bash
bash scripts/restore_postgres.sh backups/postgres/postgres_backup_comicpile_20240104_103354.sql.gz
```

**Step 5: Manual restore (alternative method)**

If the make target or script doesn't work, restore manually:

```bash
# Extract DATABASE_URL components
# From .env: DATABASE_URL=postgresql+asyncpg://comicpile:comicpile_password@localhost:5435/comicpile

# Decompress and restore
gunzip -c backups/postgres/postgres_backup_comicpile_20240104_103354.sql.gz | \
    PGPASSWORD=comicpile_password \
    psql -h localhost -p 5435 -U comicpile -d comicpile
```

### Prerequisites

The backup script requires PostgreSQL client tools:

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-client

# macOS
brew install postgresql

# RHEL/CentOS
sudo yum install postgresql
```

### Disaster Recovery with PostgreSQL Backups

**Scenario 1: Database corruption**

```bash
# Stop the application
# Drop and recreate the database
psql -h localhost -U postgres -c "DROP DATABASE comicpile;"
psql -h localhost -U postgres -c "CREATE DATABASE comicpile OWNER comicpile;"

# Restore from backup
make restore-postgres FILE=backups/postgres/postgres_backup_comicpile_20260104_103354.sql.gz
```

**Scenario 2: Migration rollback**

```bash
# List backups before migration
make list-postgres-backups

# Roll back to pre-migration state
make restore-postgres FILE=backups/postgres/postgres_backup_comicpile_20260104_080000.sql.gz

# Run migrations again (if needed)
make migrate
```

**Scenario 3: Server migration**

```bash
# On old server
make backup-postgres
scp backups/postgres/postgres_backup_comicpile_20260104_103354.sql.gz user@new-server:~/comic-pile/backups/postgres/

# On new server
make restore-postgres FILE=backups/postgres/postgres_backup_comicpile_20260104_103354.sql.gz
```

### PostgreSQL Backup vs JSON Export

| Feature | PostgreSQL Backup | JSON Export |
|---------|------------------|-------------|
| Format | Compressed SQL | JSON |
| Completeness | Full database (schema + data) | Application data only |
| Restore Speed | Fast (native) | Slower (application logic) |
| Tool Required | pg_dump/psql | Python scripts |
| Portability | PostgreSQL only | Any system |
| Use Case | Disaster recovery | Data migration/analysis |

**Recommendation:** Use PostgreSQL backups for disaster recovery and JSON exports for data analysis or migration to other systems.

### Monitoring Backup Health

Check backup script logs:

```bash
# View last backup output
bash scripts/backup_postgres.sh 2>&1 | tee backup.log
```

Successful output:
```
Database: comicpile
Host: localhost:5435
User: comicpile
Backup directory: backups/postgres
Creating backup: postgres_backup_comicpile_20260104_103354.sql.gz
Backup created successfully
File: backups/postgres/postgres_backup_comicpile_20260104_103354.sql.gz
Size: 1.2M
Verifying backup integrity...
Backup verification passed
Rotating old backups...
Current backup count: 3 (max: 10)
Backup completed successfully!
```

### Troubleshooting PostgreSQL Backups

**Issue: pg_dump not found**

```bash
# Install PostgreSQL client tools
sudo apt-get install postgresql-client  # Ubuntu/Debian
brew install postgresql                 # macOS
```

**Issue: Connection refused**

```bash
# Check PostgreSQL is running
docker compose ps

# Check database connection
psql -h localhost -p 5435 -U comicpile -d comicpile -c "SELECT 1;"
```

**Issue: Permission denied**

```bash
# Check .env file permissions
chmod 600 .env

# Check backup directory permissions
chmod 755 backups/postgres/
```

**Issue: Backup verification failed**

```bash
# Verify gzip integrity manually
gzip -t backups/postgres/postgres_backup_comicpile_20260104_103354.sql.gz

# Check available disk space
df -h
```

## Automatic Backups

The application automatically creates timestamped backups when the server starts. Backups are only created if the database has changed (uses SHA256 checksum comparison), preventing duplicate backups.

### How It Works

1. On server startup, a backup is automatically created (if enabled)
2. SHA256 checksum is computed from database content
3. If checksum matches latest backup, backup is skipped (unchanged)
4. Old backups are rotated (keeps last N backups, default: 10)
5. Logs backup success/failure to application logs

### Configuration

```bash
# .env
AUTO_BACKUP_ENABLED=true       # Enable/disable automatic backups
BACKUP_DIR=backups              # Backup directory
MAX_BACKUPS=10                 # Maximum number of backups to keep
SKIP_IF_UNCHANGED=true         # Skip backup if database unchanged
```

## Automatic Backups

The application automatically creates timestamped backups when the server starts. Backups are only created if the database has changed (uses SHA256 checksum comparison), preventing duplicate backups.

### How It Works

1. On server startup, a backup is automatically created
2. SHA256 checksum is computed from database content
3. If checksum matches latest backup, backup is skipped (unchanged)
4. Old backups are rotated (keeps last N backups, default: 10)

### Configuration

```bash
# .env
AUTO_BACKUP_ENABLED=true       # Enable/disable automatic backups
BACKUP_DIR=backups              # Backup directory
MAX_BACKUPS=10                 # Maximum number of backups to keep
SKIP_IF_UNCHANGED=true         # Skip backup if database unchanged
```

## Quick Start

```bash
# Save your current database to JSON
make save-db

# Load database from JSON (wipes current database!)
make load-db
```

## Commands

### Save Database

```bash
make save-db
# or
python -m scripts.export_db
```

Creates `db_export.json` with:
- All users
- All threads (comics)
- All sessions (reading sessions)
- All events (rolls, reads, ratings)
- All tasks
- All settings

### Load Database

```bash
make load-db
# or
python -m scripts.import_db
```

**WARNING:** This will wipe your current database and replace it with the saved state.

You'll be prompted to confirm before loading.

## Use Cases

### 1. Backup Before Breaking Changes

```bash
# Save your data
make save-db

# Make risky changes to your app
# ...

# If something breaks, restore
make load-db
```

### 2. Switch Between Development and Production

```bash
# Save production state
cp db_export.json db_export_production.json

# Do development work
# ...

# Save development state (optional)
make save-db

# Restore production
cp db_export_production.json db_export.json
make load-db
```

### 3. Sync Across Machines

```bash
# On machine A
make save-db
scp db_export.json user@machine-b:~/comic-pile/

# On machine B
make load-db
```

### 4. Version Control Your Data

```bash
# Add to git (optional)
git add db_export.json
git commit -m "Backup database"
git push
```

**Note:** Be careful committing `db_export.json` if it contains sensitive data.

## File Format

The export file is JSON with all datetime fields converted to ISO format strings:

```json
{
  "users": [...],
  "threads": [
    {
      "id": 1,
      "title": "Hellboy: Omnibus",
      "format": "Trade",
      "issues_remaining": 8,
      "queue_position": 2,
      "status": "active",
      "last_rating": 4.5,
      "last_activity_at": "2026-01-01T22:31:46.619742",
      "review_url": null,
      "last_review_at": null,
      "created_at": "2026-01-02T02:26:51.737941",
      "user_id": 1
    }
  ],
  "sessions": [...],
  "events": [...],
  "tasks": [...],
  "settings": [...]
}
```

## Best Practices

1. **Backup regularly** before risky changes
2. **Use multiple files** for different states (e.g., `db_export_before_migration.json`)
3. **Commit to git** if you want version history
4. **Keep recent backups** in case you need to roll back multiple changes
5. **Test restore** before trusting a backup

## Troubleshooting

### Export Fails

```bash
# Check database is accessible
python -c "from app.database import SessionLocal; db = SessionLocal(); print('OK')"

# Check export script has execute permissions
ls -l scripts/export_db.py
```

### Import Fails

```bash
# Make sure db_export.json exists
ls -lh db_export.json

# Check JSON is valid
python -c "import json; json.load(open('db_export.json')); print('OK')"

# Run with more verbosity
python -m scripts.import_db
```

### Wrong Data After Import

The import script **wipes** the database before loading. Make sure you're importing the right file:

```bash
# Check file modification time
ls -lh db_export.json

# Check contents
head -50 db_export.json
```

## Advanced: Manual Export/Import

### Export Specific Tables

Edit `scripts/export_db.py` to only export specific tables:

```python
# Only export threads
threads = db.query(Thread).all()
data["threads"] = [...]
```

### Import to Different Database

```bash
# Set different DATABASE_URL
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5437/comic_pile_test"
python -m scripts.import_db
```

### Merge Instead of Wipe

For non-destructive merges, edit `scripts/import_db.py` to check for existing records:

```python
existing = db.query(Thread).filter_by(id=thread_data["id"]).first()
if existing:
    # Update existing record
else:
    # Create new record
```

## Related Commands

```bash
# Seed fresh data (for testing)
make seed

# Migrate database schema
make migrate

# Run tests
make test

# Create automatic backup (with checksum and rotation)
make backup

# List all automatic backups
make list-backups

# Restore from specific automatic backup
make restore-backup FILE=backups/db_export_20240104_120530.json
```

## Automatic Backup Details

### When Backups Are Skipped

Automatic backups are skipped when:
- `AUTO_BACKUP_ENABLED=false` in environment
- Database content matches latest backup (SHA256 checksum)

When skipped, you'll see:
```
Database unchanged - skipping backup
Latest backup: db_export_20260104_103115.json (152923 bytes)
```

### Backup File Naming

Backups are named with timestamps: `db_export_YYYYMMDD_HHMMSS.json`

Example: `db_export_20240104_143022.json` = Jan 4, 2024 at 2:30:22 PM

### Viewing Backups

```bash
# List all backups with sizes
make list-backups

# Or manually
ls -lh backups/
```

Output:
```
Available backups:
-rw-rw-r-- 1 josh josh 150K Jan  4 10:31 backups/db_export_20260104_103111.json
-rw-rw-r-- 1 josh josh 150K Jan  4 10:31 backups/db_export_20260104_103115.json
-rw-rw-r-- 1 josh josh 150K Jan  4 10:33 backups/db_export_20260104_103354.json
```

### Backup Rotation

When `MAX_BACKUPS` is reached:
1. Oldest backups are deleted automatically
2. Newest backups are kept
3. Timestamped filenames make it easy to track history

Example with `MAX_BACKUPS=5`:
```
# After 7 restarts (database changing each time):
backups/db_export_20240104_100000.json  # Deleted (oldest)
backups/db_export_20240104_101500.json  # Deleted
backups/db_export_20240104_103000.json  # Kept
backups/db_export_20240104_104500.json  # Kept
backups/db_export_20240104_110000.json  # Kept
backups/db_export_20240104_113000.json  # Kept  # Newest
```

### Disaster Recovery Workflow

1. **Server crashes or database corrupted:**
   ```bash
   # Check available backups
   make list-backups

   # Restore from latest backup
   make restore-backup FILE=backups/db_export_20260104_103354.json
   ```

2. **Accidentally deleted important data:**
   ```bash
   # Find backup before the accident
   make list-backups

   # Note: Check timestamps to find right version
   ls -lt backups/ | head -5

   # Restore
   make restore-backup FILE=backups/db_export_20260104_103000.json
   ```

3. **Rollback to previous state:**
   ```bash
   # Each backup is a restore point
   # Use timestamps to track when changes happened
   make list-backups

   # Restore to state from 2 hours ago
   make restore-backup FILE=backups/db_export_20260104_080000.json
   ```

### Monitoring Backup Health

Check application logs for backup status:

```bash
# If using docker
docker-compose logs app | grep -i backup

# If running locally
# Check terminal output when server starts
```

Successful backup log:
```
INFO:app.main: Starting automatic database backup...
INFO:app.main: Database backup completed:
Backup created: backups/db_export_20260104_103354.json (152923 bytes)
Data hash: 83658216a10e95d8...
Total backups: 3 (max: 10)
Users: 1, Threads: 40, Sessions: 4, Events: 21, Tasks: 78, Settings: 1
```

Skipped backup log (unchanged):
```
Database unchanged - skipping backup
Latest backup: backups/db_export_20260104_103115.json (152923 bytes)
```

Failed backup log:
```
ERROR:app.main: Database backup failed: [error details]
```
