#!/bin/bash
set -e

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m' # No Color

echo -e "${BLUE}PostgreSQL Database Restore Script${NC}"

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
else
    echo -e "${RED}ERROR: .env file not found at $PROJECT_ROOT/.env${NC}"
    exit 1
fi

# Backup file argument
BACKUP_FILE="${1:-}"

# Parse DATABASE_URL
# Expected format: postgresql+psycopg://user:password@host:port/database
parse_database_url() {
    local url="$DATABASE_URL"

    if [ -z "$url" ]; then
        echo -e "${RED}ERROR: DATABASE_URL not set in .env${NC}"
        exit 1
    fi

    # Remove the postgresql+psycopg:// prefix
    local clean_url="${url#postgresql+psycopg://}"

    # Extract user:password
    local credentials="${clean_url%%@*}"
    PGUSER="${credentials%%:*}"
    PGPASSWORD="${credentials#*:}"
    export PGPASSWORD

    # Extract host:port/database
    local rest="${clean_url#*@}"
    PGHOST="${rest%%:*}"
    rest="${rest#*:}"
    PGPORT="${rest%%/*}"
    PGDATABASE="${rest#*/}"

    echo "Database: $PGDATABASE"
    echo "Host: $PGHOST:$PGPORT"
    echo "User: $PGUSER"
}

# Check for psql
check_psql() {
    if ! command -v psql &> /dev/null; then
        echo -e "${RED}ERROR: psql not found${NC}"
        echo -e "${YELLOW}Please install PostgreSQL client tools:${NC}"
        echo -e "  Ubuntu/Debian: sudo apt-get install postgresql-client"
        echo -e "  macOS: brew install postgresql"
        echo -e "  RHEL/CentOS: sudo yum install postgresql"
        exit 1
    fi
}

# Check for gunzip
check_gunzip() {
    if ! command -v gunzip &> /dev/null; then
        echo -e "${RED}ERROR: gunzip not found${NC}"
        echo -e "${YELLOW}Please install gzip utilities:${NC}"
        echo -e "  Ubuntu/Debian: sudo apt-get install gzip"
        echo -e "  macOS: brew install gzip"
        echo -e "  RHEL/CentOS: sudo yum install gzip"
        exit 1
    fi
}

# List available backups
list_backups() {
    local backup_dir="${BACKUP_DIR:-backups/postgres}"

    echo -e "\n${BLUE}Available backups:${NC}"
    ls -lh "$backup_dir"/postgres_backup_*.sql.gz 2>/dev/null || echo "No backups found"
}

# Verify backup file
verify_backup() {
    local filepath="$1"

    if [ ! -f "$filepath" ]; then
        echo -e "${RED}ERROR: Backup file not found: $filepath${NC}"
        echo -e "${YELLOW}Run without arguments to list available backups${NC}"
        exit 1
    fi

    echo -e "${BLUE}Verifying backup integrity...${NC}"
    if gzip -t "$filepath" 2>/dev/null; then
        local size=$(du -h "$filepath" | cut -f1)
        echo -e "${GREEN}Backup verification passed${NC}"
        echo "File: $filepath"
        echo "Size: $size"
    else
        echo -e "${RED}ERROR: Backup verification failed${NC}"
        echo -e "${RED}File may be corrupted${NC}"
        exit 1
    fi
}

# Confirm restore operation
confirm_restore() {
    local filepath="$1"

    echo -e "${RED}WARNING: This will wipe the current database and restore from backup${NC}"
    echo -e "${YELLOW}Database: $PGDATABASE${NC}"
    echo -e "${YELLOW}Backup file: $filepath${NC}"
    echo
    read -p "Are you sure you want to continue? (yes/no): " confirm

    if [ "$confirm" != "yes" ]; then
        echo -e "${YELLOW}Restore cancelled${NC}"
        exit 0
    fi
}

# Perform restore
restore_backup() {
    local filepath="$1"

    echo -e "${GREEN}Restoring database...${NC}"

    if gunzip -c "$filepath" | psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --quiet; then
        echo -e "${GREEN}Database restored successfully${NC}"
        return 0
    else
        echo -e "${RED}ERROR: Database restore failed${NC}"
        return 1
    fi
}

# Verify database after restore
verify_database() {
    echo -e "${BLUE}Verifying database after restore...${NC}"

    local thread_count=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -c "SELECT COUNT(*) FROM thread;" 2>/dev/null | tr -d ' ')

    if [ -n "$thread_count" ]; then
        echo -e "${GREEN}Database verification passed${NC}"
        echo "Threads: $thread_count"
        return 0
    else
        echo -e "${YELLOW}Warning: Could not verify database contents${NC}"
        echo "Restore may have completed but verification failed"
        return 0
    fi
}

# Show usage
usage() {
    echo "Usage: $0 <backup-file>"
    echo
    echo "Arguments:"
    echo "  backup-file    Path to backup file (e.g., backups/postgres/postgres_backup_comicpile_20240104_103354.sql.gz)"
    echo
    echo "Examples:"
    echo "  $0 backups/postgres/postgres_backup_comicpile_20240104_103354.sql.gz"
    echo "  $0 backups/postgres/\$(ls -t backups/postgres/postgres_backup_*.sql.gz | head -1)"
    echo
    echo "To list available backups, run without arguments:"
    echo "  $0"
}

# Main execution
main() {
    # If no arguments, list backups and exit
    if [ -z "$BACKUP_FILE" ]; then
        parse_database_url
        list_backups
        echo
        usage
        exit 0
    fi

    # Check prerequisites
    parse_database_url
    check_psql
    check_gunzip

    # Verify backup file exists
    verify_backup "$BACKUP_FILE"

    # Confirm restore
    confirm_restore "$BACKUP_FILE"

    # Perform restore
    restore_backup "$BACKUP_FILE"

    # Verify database
    verify_database

    echo -e "\n${GREEN}Restore completed successfully!${NC}"
}

# Run main function
main "$@"
