#!/bin/bash
set -e

# Rollback helper for the current Dockerized PostgreSQL environment.
# Usage: ./scripts/rollback.sh <rollback-type> [options]

ROLLBACK_TYPE="${1:-help}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups"
mkdir -p "$BACKUP_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

rollback_database() {
    log_warn "Automated database down-migrations are not supported."
    log_info "The Rust refinery runner (comicpile-migrate) supports forward migrations only (up/plan)."
    log_info "To apply pending migrations: cargo run --locked -p comicpile-migrate -- up"
    log_info "To inspect migration state:   cargo run --locked -p comicpile-migrate -- plan"
    log_info "For data recovery, restore a PostgreSQL backup with: ./scripts/rollback.sh restore <backup-file>"
    exit 1
}

rollback_git() {
    local COMMIT_HASH="${2:-HEAD~1}"
    log_info "Rolling back git to $COMMIT_HASH..."
    log_info "Creating backup branch..."
    git branch "pre-rollback-backup-$TIMESTAMP"
    git reset --hard "$COMMIT_HASH"
    log_info "Git rollback complete"
    log_info "Backup branch: pre-rollback-backup-$TIMESTAMP"
}

rollback_docker() {
    local IMAGE_ID="${2}"
    log_info "Rolling back Docker image..."
    if [ -z "$IMAGE_ID" ]; then
        log_error "Please provide image ID: ./scripts/rollback.sh docker <image-id>"
        exit 1
    fi
    log_info "Stopping containers..."
    docker compose down
    log_info "Retagging previous image..."
    docker tag "$IMAGE_ID" comic-pile:latest
    log_info "Restarting containers..."
    docker compose up -d
    log_info "Docker rollback complete"
}

rollback_full() {
    log_warn "This will rollback git and reset local Docker services."
    log_warn "Database down-migrations are not automated; restore a backup if you need data recovery."
    read -p "Are you sure? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        log_info "Rollback cancelled"
        exit 0
    fi
    log_info "Starting full rollback..."
    log_info "Step 1: Rolling back git..."
    rollback_git "${2:-HEAD~1}"
    log_info "Step 2: Rebuilding Docker images..."
    docker compose build --no-cache
    log_info "Step 3: Restarting containers..."
    docker compose down
    docker compose up -d
    log_info "Full rollback complete (database schema/data was not down-migrated)"
}

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
    log_info "Restoring database..."
    docker compose exec -T db psql -U comicpile -d comicpile < "$BACKUP_FILE"
    log_info "Restore complete"
}

show_help() {
    cat << EOF
Rollback Script for Dockerized PostgreSQL Environment

Usage: ./scripts/rollback.sh <command> [options]

Commands:
    database           Explain database rollback limitations (no automated down-migrations)
    git [commit]       Rollback git to previous commit (default: HEAD~1)
    docker <image-id>  Rollback to previous Docker image
    full [commit]      Full rollback (git + docker rebuild/restart; no database down-migration)
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
