#!/bin/bash
set -e

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m' # No Color

echo -e "${BLUE}PostgreSQL Database Backup Script${NC}"

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

# Backup configuration (can be overridden with env vars)
BACKUP_DIR="${BACKUP_DIR:-backups/postgres}"
MAX_BACKUPS="${MAX_BACKUPS:-10}"
DATABASE_URL="${DATABASE_URL:-}"

# Parse DATABASE_URL
# Supported formats: postgresql+asyncpg://..., postgresql+psycopg://..., postgresql://..., postgres://...
parse_database_url() {
    local url="$DATABASE_URL"
    
    if [ -z "$url" ]; then
        echo -e "${RED}ERROR: DATABASE_URL not set in .env${NC}"
        exit 1
    fi
    
    # Remove URL scheme prefix
    local clean_url="$url"
    clean_url="${clean_url#postgresql+asyncpg://}"
    clean_url="${clean_url#postgresql+psycopg://}"
    clean_url="${clean_url#postgresql://}"
    clean_url="${clean_url#postgres://}"
    
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

# Check for pg_dump
check_pg_dump() {
    if ! command -v pg_dump &> /dev/null; then
        echo -e "${RED}ERROR: pg_dump not found${NC}"
        echo -e "${YELLOW}Please install PostgreSQL client tools:${NC}"
        echo -e "  Ubuntu/Debian: sudo apt-get install postgresql-client"
        echo -e "  macOS: brew install postgresql"
        echo -e "  RHEL/CentOS: sudo yum install postgresql"
        exit 1
    fi
}

# Create backup directory
create_backup_dir() {
    mkdir -p "$BACKUP_DIR"
    echo "Backup directory: $BACKUP_DIR"
}

# Create backup
create_backup() {
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local filename="postgres_backup_${PGDATABASE}_${timestamp}.sql.gz"
    local filepath="$BACKUP_DIR/$filename"
    
    echo -e "${GREEN}Creating backup: $filename${NC}"
    
    if pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
        --no-owner --no-acl --verbose \
        2>&1 | gzip > "$filepath"; then
        
        local size=$(du -h "$filepath" | cut -f1)
        echo -e "${GREEN}Backup created successfully${NC}"
        echo "File: $filepath"
        echo "Size: $size"
        
        # Verify backup
        echo -e "${BLUE}Verifying backup integrity...${NC}"
        if gzip -t "$filepath" 2>/dev/null; then
            echo -e "${GREEN}Backup verification passed${NC}"
        else
            echo -e "${RED}ERROR: Backup verification failed${NC}"
            rm "$filepath"
            exit 1
        fi
        
        return 0
    else
        echo -e "${RED}ERROR: Backup creation failed${NC}"
        return 1
    fi
}

# Rotate old backups
rotate_backups() {
    echo -e "${BLUE}Rotating old backups...${NC}"
    
    # Count backups
    local backup_count=$(ls -1 "$BACKUP_DIR"/postgres_backup_*.sql.gz 2>/dev/null | wc -l)
    echo "Current backup count: $backup_count (max: $MAX_BACKUPS)"
    
    if [ "$backup_count" -gt "$MAX_BACKUPS" ]; then
        local to_delete=$((backup_count - MAX_BACKUPS))
        echo "Deleting $to_delete old backup(s)"
        
        # Delete oldest backups
        ls -t "$BACKUP_DIR"/postgres_backup_*.sql.gz | tail -n "$to_delete" | while read -r file; do
            echo "Deleting: $file"
            rm "$file"
        done
    fi
}

# List backups
list_backups() {
    echo -e "\n${BLUE}Available backups:${NC}"
    ls -lh "$BACKUP_DIR"/postgres_backup_*.sql.gz 2>/dev/null || echo "No backups found"
}

# Main execution
main() {
    parse_database_url
    check_pg_dump
    create_backup_dir
    create_backup
    rotate_backups
    list_backups
    
    echo -e "\n${GREEN}Backup completed successfully!${NC}"
}

# Run main function
main
