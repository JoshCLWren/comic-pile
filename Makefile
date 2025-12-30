.PHONY: help init lint pytest sync venv githook install-githook
.PHONY: create-phase1 create-phase2 create-phase3 create-phase4 create-phase5 create-phase6 create-phase7 create-phase8 create-phase9
.PHONY: merge-phase1 merge-phase2 merge-phase3 merge-phase4 merge-phase5 merge-phase6 merge-phase7 merge-phase8 merge-phase9
.PHONY: dev seed migrate worktrees status

# Configuration
PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib

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

lint:  ## Run code linting
	bash scripts/lint.sh

install-githook:  ## Install pre-commit hook for new developers
	@mkdir -p .git/hooks
	@cp .githooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Pre-commit hook installed to .git/hooks/pre-commit"

githook: install-githook  ## Run lint checks manually (installs pre-commit hook if missing)
	bash scripts/lint.sh

pytest:  ## Run tests
	pytest

sync:  ## Install dependencies
	uv sync --all-extras

venv:  ## Create virtual environment
	uv venv

create-phase1:  ## Create Phase 1 branch
	@git checkout main && git pull && git checkout -b phase/1-cleanup-fastapi-setup

create-phase2:  ## Create Phase 2 branch
	@git checkout main && git pull && git checkout -b phase/2-database-models

create-phase3:  ## Create Phase 3 branch
	@git checkout main && git pull && git checkout -b phase/3-rest-api

create-phase4:  ## Create Phase 4 branch
	@git checkout main && git pull && git checkout -b phase/4-templates-views

create-phase5:  ## Create Phase 5 branch
	@git checkout main && git pull && git checkout -b phase/5-interactive-features

create-phase6:  ## Create Phase 6 branch
	@git checkout main && git pull && git checkout -b phase/6-testing

create-phase7:  ## Create Phase 7 branch
	@git checkout main && git pull && git checkout -b phase/7-data-import

create-phase8:  ## Create Phase 8 branch
	@git checkout main && git pull && git checkout -b phase/8-polish

create-phase9:  ## Create Phase 9 branch
	@git checkout main && git pull && git checkout -b phase/9-documentation

merge-phase1:  ## Merge Phase 1 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/1-cleanup-fastapi-setup && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase2:  ## Merge Phase 2 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/2-database-models && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase3:  ## Merge Phase 3 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/3-rest-api && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase4:  ## Merge Phase 4 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/4-templates-views && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase5:  ## Merge Phase 5 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/5-interactive-features && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase6:  ## Merge Phase 6 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/6-testing && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase7:  ## Merge Phase 7 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/7-data-import && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase8:  ## Merge Phase 8 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/8-polish && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

merge-phase9:  ## Merge Phase 9 to main
	@git checkout main && git pull && \
	git merge --no-ff phase/9-documentation && \
	$(MAKE) pytest && \
	$(MAKE) lint && \
	pyright . && \
	git push origin main

dev:  ## Run development server with hot reload
	@echo "Starting FastAPI development server on http://0.0.0.0:8000"
	@uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

seed:  ## Seed database with sample data
	@echo "Seeding database with Faker data..."
	@python -m scripts.seed_data

migrate:  ## Run database migrations
	@echo "Running database migrations..."
	@alembic upgrade head

worktrees:  ## List all git worktrees
	@echo "Git worktrees:"
	@git worktree list

status:  ## Show current task status
	@cat TASKS.md | head -100
