.PHONY: help init lint pytest sync venv githook install-githook
.PHONY: create-phase1 create-phase2 create-phase3 create-phase4 create-phase5 create-phase6 create-phase7 create-phase8 create-phase9
.PHONY: merge-phase1 merge-phase2 merge-phase3 merge-phase4 merge-phase5 merge-phase6 merge-phase7 merge-phase8 merge-phase9
.PHONY: dev test seed migrate worktrees status test-integration deploy-prod dev-all dev-frontend

# Configuration
PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib

# Port configuration - Port allocation rules:
# - Main repo (task API source of truth): 8000
# - Agent worktree 1: 8001
# - Agent worktree 2: 8002
# - Agent worktree 3: 8003
PORT ?= 8000

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

init:  ## Initialize project with new name (Usage: make init NAME=your-project)
	@if [ -z "$(NAME)" ]; then echo "Usage: make init NAME=your-project"; exit 1; fi
	@echo "Initializing project as $(NAME)..."
	@sed -i.bak "s/python-starter-template/$(NAME)/g" pyproject.toml && rm pyproject.toml.bak
	@sed -i.bak "s/example_module/$(NAME)/g" pyproject.toml && rm pyproject.toml.bak
	@if [ -d "example_module" ]; then \
		echo "Renaming example_module to $(NAME)..."; \
		mv example_module $(NAME); \
		find . -type f -name "*.py" -exec sed -i.bak "s/from example_module/from $(NAME)/g" {} +; \
		find . -type f -name "*.py.bak" -delete; \
	fi
	@echo "Project initialized as $(NAME)"
	@echo "Run 'uv sync --all-extras' to install dependencies"

lint:  ## Run code linting (ruff and pyright)
	bash scripts/lint.sh

install-githook:  ## Install pre-commit hook for new developers
	@mkdir -p .git/hooks
	@cp .githooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed to .git/hooks/pre-commit"

githook: install-githook  ## Run lint checks manually (installs pre-commit hook if missing)
	bash scripts/lint.sh

test:  ## Run tests with coverage (pytest --cov=comic_pile --cov-report=term-missing)
	pytest --cov=comic_pile --cov-report=term-missing

pytest:  ## Run tests (pytest)
	pytest

sync:  ## Install dependencies via uv
	uv sync --all-extras

venv:  ## Create virtual environment with uv
	uv venv

create-phase1:  ## Create Phase 1 branch (phase/1-cleanup-fastapi-setup)
	@git checkout main && git pull && git checkout -b phase/1-cleanup-fastapi-setup

create-phase2:  ## Create Phase 2 branch (phase/2-database-models)
	@git checkout main && git pull && git checkout -b phase/2-database-models

create-phase3:  ## Create Phase 3 branch (phase/3-rest-api)
	@git checkout main && git pull && git checkout -b phase/3-rest-api

create-phase4:  ## Create Phase 4 branch (phase/4-templates-views)
	@git checkout main && git pull && git checkout -b phase/4-templates-views

create-phase5:  ## Create Phase 5 branch (phase/5-interactive-features)
	@git checkout main && git pull && git checkout -b phase/5-interactive-features

create-phase6:  ## Create Phase 6 branch (phase/6-testing)
	@git checkout main && git pull && git checkout -b phase/6-testing

create-phase7:  ## Create Phase 7 branch (phase/7-data-import)
	@git checkout main && git pull && git checkout -b phase/7-data-import

create-phase8:  ## Create Phase 8 branch (phase/8-polish)
	@git checkout main && git pull && git checkout -b phase/8-polish

create-phase9:  ## Create Phase 9 branch (phase/9-documentation)
	@git checkout main && git pull && git checkout -b phase/9-documentation

merge-phase1:  ## Merge Phase 1 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/1-cleanup-fastapi-setup && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase2:  ## Merge Phase 2 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/2-database-models && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase3:  ## Merge Phase 3 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/3-rest-api && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase4:  ## Merge Phase 4 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/4-templates-views && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase5:  ## Merge Phase 5 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/5-interactive-features && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase6:  ## Merge Phase 6 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/6-testing && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase7:  ## Merge Phase 7 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/7-data-import && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase8:  ## Merge Phase 8 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/8-polish && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase9:  ## Merge Phase 9 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/9-documentation && \
	$(MAKE) test && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

dev:  ## Run development server with hot reload (uvicorn app.main:app --reload)
	@echo "Starting FastAPI development server on http://0.0.0.0:${PORT}"
	@uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --reload

seed:  ## Seed database with sample data (python -m scripts.seed_data)
	@echo "Seeding database with Faker data..."
	@python -m scripts.seed_data

migrate:  ## Run database migrations (alembic upgrade head)
	@echo "Running database migrations..."
	@alembic upgrade head

worktrees:  ## List all git worktrees
	@echo "Git worktrees:"
	@git worktree list

status:  ## Show current task status
	@cat TASKS.md | head -100

test-integration:  ## Run Playwright integration tests
	@echo "Running Playwright integration tests..."
	@pytest tests_e2e/ -m integration --headed=false --video=retain-on-failure
 
save-db:  ## Save database to JSON (python -m scripts.export_db)
	@echo "Exporting database to db_export.json..."
	@python -m scripts.export_db
	@echo "Database saved to db_export.json"

load-db:  ## Load database from JSON (python -m scripts.import_db)
	@echo "WARNING: This will wipe the current database and restore from db_export.json"
	@read -p "Are you sure? (yes/no): " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		echo "Loading database from db_export.json..."; \
		python -m scripts.import_db; \
		echo "Database restored from db_export.json"; \
	else \
		echo "Load cancelled"; \
	fi

backup:  ## Create timestamped backup with rotation (python -m scripts.backup_database)
	@echo "Creating timestamped backup..."
	@python -m scripts.backup_database
	@echo "Backup complete"

list-backups:  ## List all timestamped backups
	@echo "Available backups:"
	@ls -lh backups/db_export_*.json 2>/dev/null || echo "No backups found"

restore-backup:  ## Restore from a specific backup (make restore-backup FILE=backups/db_export_20240104_102530.json)
	@echo "WARNING: This will wipe the current database and restore from $$FILE"
	@read -p "Are you sure? (yes/no): " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		if [ -f "$$FILE" ]; then \
			cp "$$FILE" db_export.json; \
			python -m scripts.import_db; \
			echo "Database restored from $$FILE"; \
		else \
			echo "Error: File $$FILE not found"; \
		fi \
	else \
		echo "Restore cancelled"; \
	fi

docker-build:  ## Build Docker images (docker compose build)
	@echo "Building Docker images..."
	@docker compose build

docker-up:  ## Start Docker containers (docker compose up -d)
	@echo "Starting Docker containers..."
	@docker compose up -d

docker-down:  ## Stop Docker containers (docker compose down)
	@echo "Stopping Docker containers..."
	@docker compose down

docker-logs:  ## Show Docker container logs (docker compose logs -f)
	@echo "Showing Docker container logs..."
	@docker compose logs -f

docker-migrate:  ## Run database migrations in Docker container
	@echo "Running database migrations in Docker..."
	@docker compose exec -T app .venv/bin/alembic upgrade head

docker-test:  ## Run pytest in Docker container
	@echo "Running tests in Docker container..."
	@docker compose exec -T app .venv/bin/pytest --cov=comic_pile --cov-report=term-missing

docker-health:  ## Check Docker container health status
	@echo "Checking Docker container health..."
	@docker compose ps

backup-postgres:  ## Create PostgreSQL backup with pg_dump
	@bash scripts/backup_postgres.sh

restore-postgres:  ## Restore PostgreSQL from backup (make restore-postgres FILE=backups/postgres/postgres_backup_YYYYMMDD_HHMMSS.sql.gz)
	@bash scripts/restore_postgres.sh $(FILE)

list-postgres-backups:  ## List all PostgreSQL backups
	@echo "Available PostgreSQL backups:"
	@ls -lh backups/postgres/postgres_backup_*.sql.gz 2>/dev/null || echo "No PostgreSQL backups found"

deploy-prod:  ## Deploy to Railway production
	@echo "Building React frontend..."
	@cd frontend && npm run build && cd ..
	@echo "Committing and pushing to GitHub..."
	@git add -A
	@git commit -m "$$(date -u +'%Y-%m-%d %H:%M:%S') production deploy" || echo "No changes to commit"
	@git push origin main
	@echo "Deploying to Railway..."
	@railway up --detach
	@sleep 60
	@echo "Checking deployment status..."
	@railway status
	@echo "Testing health endpoint..."
	@curl -s https://app-production-72b9.up.railway.app/health || echo "Health check failed"

dev-all:  ## Run both frontend and backend dev servers (Vite proxies /api to backend)
	@echo "Checking for running servers..."
	@BACKEND_PID=$$(lsof -t -i:8000 2>/dev/null || echo ""); \
	if [ -n "$$BACKEND_PID" ]; then \
		echo "Backend already running on port 8000 (PID: $$BACKEND_PID)"; \
	else \
		echo "Starting backend on port 8000..."; \
		uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload & \
		BACKEND_PID=$$!; \
	fi; \
	@FRONTEND_PID=$$(lsof -t -i:5173 2>/dev/null || echo ""); \
	if [ -n "$$FRONTEND_PID" ]; then \
		echo "Frontend already running on port 5173 (PID: $$FRONTEND_PID)"; \
	else \
		echo "Starting frontend on port 5173..."; \
		cd frontend && npm run dev & \
		FRONTEND_PID=$$!; \
	fi; \
	@echo ""; \
	@echo "Backend: http://localhost:8000 (PID: $$BACKEND_PID)"; \
	@echo "Frontend: http://localhost:5173 (PID: $$FRONTEND_PID)"; \
	@echo ""; \
	@echo "Press Ctrl+C to stop"; \
	@sleep 2; \
	@trap "kill $$BACKEND_PID 2>/dev/null; kill $$FRONTEND_PID 2>/dev/null" EXIT; \
	@wait

dev-frontend:  ## Run frontend dev server only (npm run dev in frontend/)
	@echo "Checking for running servers..."
	@FRONTEND_PID=$$(lsof -t -i:5173 2>/dev/null || echo ""); \
	if [ -n "$$FRONTEND_PID" ]; then \
		echo "Frontend already running on port 5173 (PID: $$FRONTEND_PID)"; \
	else \
		echo "Starting Vite dev server on http://localhost:5173..."; \
		cd frontend && npm run dev; \
	fi
