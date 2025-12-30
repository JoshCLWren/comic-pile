.PHONY: help init lint pytest sync venv run smoke clean-build build build-onedir install install-bin install-desktop mime-query redo ci-test-debian ci-test-local ci-build-image githook install-githook

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
