.PHONY: help init lint pytest sync venv run smoke clean-build build build-onedir install install-bin install-desktop mime-query redo ci-test-debian ci-test-local ci-build-image githook install-githook
.PHONY: create-phase1 create-phase2 create-phase3 create-phase4 create-phase5 create-phase6 create-phase7 create-phase8 create-phase9
.PHONY: merge-phase1 merge-phase2 merge-phase3 merge-phase4 merge-phase5 merge-phase6 merge-phase7 merge-phase8 merge-phase9
.PHONY: cleanup-phase1 cleanup-phase2 cleanup-phase3 cleanup-phase4 cleanup-phase5 cleanup-phase6 cleanup-phase7 cleanup-phase8 cleanup-phase9
.PHONY: dev seed migrate worktrees status update-tasks

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

profile-cbz:  ## Profile CBZ launch performance (Usage: make profile-cbz FILE=path/to/comic.cbz)
	@if [ -z "$(FILE)" ]; then echo "Usage: make profile-cbz FILE=path/to/comic.cbz"; exit 1; fi
	@echo "Profiling CBZ launch..."
	@time uv run --active python cdisplayagain.py "$(FILE)"

profile-cbr:  ## Profile CBR launch performance (Usage: make profile-cbr FILE=path/to/comic.cbr)
	@if [ -z "$(FILE)" ]; then echo "Usage: make profile-cbr FILE=path/to/comic.cbr"; exit 1; fi
	@echo "Profiling CBR launch..."
	@time uv run --active python cdisplayagain.py "$(FILE)"

sync:  ## Install dependencies
	uv sync --all-extras

venv:  ## Create virtual environment
	uv venv

run:  ## Run the app (Usage: make run FILE=path/to/comic.cbz)
	@if [ -z "$(FILE)" ]; then echo "Usage: make run FILE=path/to/comic.cbz"; exit 1; fi
	python cdisplayagain.py "$(FILE)"

smoke:  ## Run manual smoke test checklist
	@if [ -z "$(FILE)" ]; then echo "Usage: make smoke FILE=path/to/comic.cbz"; exit 1; fi
	@echo "Manual smoke test checklist:"
	@echo "- Open both CBZ and CBR archives (CBR requires unar)"
	@echo "- Page through images to confirm ordering"
	@echo "- Toggle fit-to-screen, fit-to-width, and zoom modes"
	@echo "- Confirm temp directories are cleaned on exit"
	python cdisplayagain.py "$(FILE)"

clean-build:  ## Clean build artifacts
	rm -rf build dist *.spec __pycache__ .pytest_cache

build: clean-build  ## Build single-file executable (slower startup)
	pyinstaller --onefile --name cdisplayagain cdisplayagain.py

build-onedir: clean-build  ## Build directory bundle (faster startup)
	pyinstaller --onedir --name cdisplayagain cdisplayagain.py

install: install-bin install-desktop  ## Install everything

install-bin:  ## Install binary to system
	@if [ -f dist/cdisplayagain ]; then \
		echo "Installing onefile binary to $(BINDIR)/cdisplayagain"; \
		install -d $(BINDIR); \
		install -m 0755 dist/cdisplayagain $(BINDIR)/cdisplayagain; \
	elif [ -f dist/cdisplayagain/cdisplayagain ]; then \
		echo "Installing onedir bundle to $(LIBDIR)/cdisplayagain and wrapper to $(BINDIR)/cdisplayagain"; \
		rm -rf $(LIBDIR)/cdisplayagain; \
		install -d $(LIBDIR)/cdisplayagain; \
		cp -a dist/cdisplayagain/* $(LIBDIR)/cdisplayagain/; \
		install -d $(BINDIR); \
		printf '%s\n' '#!/usr/bin/env sh' 'exec $(LIBDIR)/cdisplayagain/cdisplayagain "$$@"' > $(BINDIR)/cdisplayagain; \
		chmod 0755 $(BINDIR)/cdisplayagain; \
	else \
		echo "No dist output found. Run 'make build' or 'make build-onedir' first."; \
		exit 1; \
	fi

install-desktop:  ## Install desktop entry
	mkdir -p $(HOME)/.local/share/applications
	printf '%s\n' \
		'[Desktop Entry]' \
		'Type=Application' \
		'Name=cdisplayagain' \
		'Exec=$(BINDIR)/cdisplayagain %f' \
		'Terminal=false' \
		'Categories=Graphics;Viewer;' \
		'MimeType=application/x-cbz;application/x-cbr;' \
		> $(HOME)/.local/share/applications/cdisplayagain.desktop
	update-desktop-database $(HOME)/.local/share/applications || true
	xdg-mime default cdisplayagain.desktop application/x-cbz
	xdg-mime default cdisplayagain.desktop application/x-cbr

mime-query:  ## Query current MIME associations
	@echo "CBZ:" $$(xdg-mime query default application/x-cbz)
	@echo "CBR:" $$(xdg-mime query default application/x-cbr)

redo: build-onedir install-bin  ## Rebuild and run (Usage: make redo FILE=...)
	@if [ -n "$(FILE)" ]; then \
		$(BINDIR)/cdisplayagain "$(FILE)"; \
	else \
		echo "Usage: make redo FILE=path/to/comic.cbz"; \
	fi

ci-test-local:  ## Run CI-like tests locally (requires xvfb and libvips)
	@echo "Running CI-like test locally..."
	@if ! command -v xvfb-run >/dev/null 2>&1; then \
		echo "WARNING: xvfb-run not found. Running without virtual display..."; \
		pytest tests/ -q --tb=short 2>&1 | tee ci-test-output.log; \
	else \
		xvfb-run -a pytest tests/ -q --tb=short 2>&1 | tee ci-test-output.log; \
	fi
	@if [ -f ci-test-output.log ]; then \
		echo ""; \
		echo "=== CI Test Output Summary ==="; \
		grep -E "passed|failed|ERROR|coverage" ci-test-output.log | tail -10; \
	fi

ci-build-image:  ## Build/rebuild cached debian image
	@echo "Building cached debian image..."
	@docker compose build ci

ci-test-debian:  ## Run tests in cached debian container (like GitHub CI)
	@echo "Running tests in cached debian container..."
	@if ! docker image inspect cdisplayagain-ci:13 >/dev/null 2>&1; then \
		echo "Cached image not found, building..."; \
		$(MAKE) ci-build-image; \
	fi
	@docker run --rm \
		-v "$(CURDIR):/app" \
		-v "$(CURDIR)/.venv:/app/.venv" \
		-w /app \
		-e PATH="/root/.local/bin:$$PATH" \
		cdisplayagain-ci:13 \
		bash -c 'source .venv/bin/activate && uv sync --all-extras && timeout 300 xvfb-run -a --server-args="-screen 0 1280x1024x24" pytest tests/ -q --tb=short' \
		2>&1 | tee ci-test-debian-output.log
	@if [ -f ci-test-debian-output.log ]; then \
		echo "=== CI Test Output Summary ==="; \
		grep -E "passed|failed|ERROR|coverage" ci-test-debian-output.log | tail -10; \
	fi

ci-check:  ## Check if CI prerequisites are installed
	@echo "Checking CI prerequisites..."
	@echo "libvips: $$(dpkg -l | grep -q libvips && echo 'INSTALLED' || echo 'NOT FOUND')"
	@echo "xvfb: $$(command -v xvfb-run && echo 'INSTALLED' || echo 'NOT FOUND')"
	@echo "python3-tk: $$(dpkg -l | grep -q python3-tk && echo 'INSTALLED' || echo 'NOT FOUND')"
	@echo "docker: $$(command -v docker && echo 'INSTALLED' || echo 'NOT FOUND')"

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
