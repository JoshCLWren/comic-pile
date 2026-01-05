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
    log_info "Starting database rollback..."
    docker-compose exec -T db pg_dump -U comicpile comicpile > "$BACKUP_DIR/emergency_before_rollback_$TIMESTAMP.sql"
    log_info "Rolling back migrations..."
    docker-compose exec app alembic downgrade base
    log_info "Database rollback complete"
    log_info "Emergency backup: $BACKUP_DIR/emergency_before_rollback_$TIMESTAMP.sql"
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
    docker-compose down
    log_info "Retagging previous image..."
    docker tag "$IMAGE_ID" comic-pile:latest
    log_info "Restarting containers..."
    docker-compose up -d
    log_info "Waiting for health check..."
    sleep 10
    if curl -f http://localhost:8000/health; then
        log_info "Docker rollback successful"
    else
        log_error "Health check failed after rollback"
        exit 1
    fi
}

rollback_full() {
    log_warn "This will rollback git, rebuild Docker images, and reset database"
    read -p "Are you sure? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        log_info "Rollback cancelled"
        exit 0
    fi
    log_info "Starting full system rollback..."
    log_info "Step 1: Rolling back git..."
    rollback_git "${2:-HEAD~1}"
    log_info "Step 2: Rebuilding Docker images..."
    docker-compose build --no-cache
    log_info "Step 3: Stopping containers..."
    docker-compose down
    log_info "Step 4: Rolling back database..."
    rollback_database
    log_info "Step 5: Restarting services..."
    docker-compose up -d
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
    log_info "Stopping application..."
    docker-compose stop app
    log_info "Restoring database..."
    docker-compose exec -T db psql -U comicpile -d comicpile < "$BACKUP_FILE"
    log_info "Starting application..."
    docker-compose start app
    log_info "Restore complete"
}

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
