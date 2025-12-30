# Repository Guidelines

## Project Ethos
- **Honor the original experience:** Preserve CDisplay's fast, lightweight, and keyboard-first feel rather than reinventing the workflow.
- **Modernize without bloat:** Adopt Python conveniences and Tk widgets only when they simplify maintenance; avoid bolting on features that slow startup or clutter the UI.
- **Respect readers' libraries:** Never mutate archives, keep temporary files contained and cleaned, and surface errors before data loss can occur.
- **Prefer clarity over cleverness:** Write explicit helpers, document design decisions in pull requests, and leave the code approachable for hobbyist contributors.
- **Cross-platform empathy:** Test on at least one non-Windows platform, call out external dependencies like `unar`, and avoid shell-specific shortcuts.

## Project Structure & Module Organization
The viewer lives entirely in the repository root. `cdisplayagain.py` exposes the CLI-oriented entrypoint with a `PageSource` abstraction and rendering loop built around `Archive` subclasses for CBZ/CBR handling. Tooling metadata (`pyproject.toml`, `uv.lock`) defines the Pillow and rarfile dependencies; assets are loaded directly from archives at runtime, so there is no static `assets/` directory. Expect any future modules (tests, components, helpers) to sit beside these files unless a new package directory is created.

## Build, Test, and Development Commands
- `make init NAME=your-project`: initialize the template with your project name (renames module and updates config).
- `source .venv/bin/activate`: activate the virtual environment (do this once per session).
- `uv sync --all-extras`: install dependencies via uv.
- `python main.py`: run the main entrypoint.
- `pytest`: run tests.
- `make pytest`: run the test suite.
- `make lint`: run ruff.

## Getting Started
When cloning this template for a new project:
1. Run `make init NAME=your-project` to rename the module and update config
2. Run `uv sync --all-extras` to install all dependencies
3. Run `source .venv/bin/activate` to activate the virtual environment
4. Start building your project!

## Git Worktrees (Parallel Work)
Use git worktrees to work on multiple cards in parallel without branch conflicts:
- Create a branch per card: `git switch -c card/short-slug`
- Add a worktree: `git worktree add ../cdisplayagain-<slug> card/short-slug`
- Work only in that worktree for the card; run tests there.
- Keep the branch updated: `git fetch` then `git rebase origin/main` (or merge).
- When merged, remove it: `git worktree remove ../cdisplayagain-<slug>`
- Clean stale refs: `git worktree prune`
- WIP limit: 3 cards total in progress across all worktrees.

## Test Coverage Requirements
- Current target: 96% coverage threshold (configured in `pyproject.toml`)
- Coverage milestones: 68% ✅ → 74% ✅ → 80% ✅ → 85% ✅ → 90% ✅ → 95% ✅ → 96% 🎯 → 100%
- Always run `pytest --cov=cdisplayagain --cov-report=term-missing` to check missing coverage
- When touching logic or input handling, ensure tests are added to maintain coverage
- Strategies for increasing coverage:
  - Add tests for remaining uncovered edge cases
  - Add tests for complex error handling paths
  - Add tests for platform-specific code paths

## Performance Guidelines
- Image resizing (LANCZOS resampling) is the primary bottleneck (~65% of CPU time)
- Archive extraction overhead is minimal: ~0.01s for ZIP, ~0.5s for RAR via unar
- When optimizing, prioritize: 1) Adaptive resampling during scroll, 2) Async loading pipeline
- Use `PerfTimer` context manager for timing operations: `with PerfTimer("operation_name"):`
- Use `perf_log()` to log performance metrics when `CDISPLAYAGAIN_PERF=1` is set
- Consider switching to BILINEAR/NEAREST during rapid scrolling, apply LANCZOS only when image settles

## Parity Implementation Pattern
When implementing features from docs/PARITY.md:
- Many features have API-only placeholder methods in cdisplayagain.py (lines 928-1006)
- These placeholders serve as API contracts and maintain parity test compatibility
- Remove the `return None` or `pass` when implementing
- Keep method signatures intact to avoid breaking changes
- Update tests to verify real functionality instead of placeholder existence
- Update docs/PARITY.md to move items from "API-Only" to "Completed Parity"
- Maintain the "fast, lightweight" ethos - adding features shouldn't slow startup

## Coding Style & Naming Conventions
Follow standard PEP 8 spacing (4 spaces, 100-character soft wrap) and favor descriptive snake_case for functions and variables (`natural_key`, `open_archive`). Retain the current pattern of dataclasses (`Archive`, `PageSource`) for typed data containers and keep public functions annotated with precise types. Prefer explicit helper names (e.g., `load_cbz`) and guard Tk callbacks with early returns rather than nesting.

Ruff configuration (from `pyproject.toml`):
- Line length: 100 characters
- Python version: 3.13
- Enabled rules: E, F, I, N, UP, B, C4, D, ANN401
- Ignored: D203, D213, E501
- Code comments are discouraged - prefer clear code and commit messages

## Pre-commit Hook
A pre-commit hook is installed in `.git/hooks/pre-commit` that automatically runs:
- Check for type/linter ignores in staged files
- Run the shared lint script (`scripts/lint.sh`)

The lint script runs:
- Python compilation check
- Ruff linting
- Any type usage check (ruff ANN401 rule)
- Pyright type checking

The hook will block commits containing `# type: ignore`, `# noqa`, `# ruff: ignore`, or `# pylint: ignore`.

To test the hook manually: `make githook` or `bash scripts/lint.sh`

## Code Quality Standards
- Run linting after each change:
  - `make lint` or `bash scripts/lint.sh`
- Use specific types instead of `Any` in type annotations (ruff ANN401 rule)
- Run tests when you touch logic or input handling:
  - `pytest`
- Perform manual smoke checks (CBZ + CBR) before sharing UI changes:
  - Open a sample archive, page through images, toggle fit/zoom, and confirm
    temporary directories are cleaned.
- Always write a regression test when fixing a bug.
- If you break something while fixing it, fix both in the same PR.
- Do not check in sample comics or proprietary content.
- Do not use in-line comments to disable linting or type checks.
- Do not narrate your code with comments; prefer clear code and commit messages.

## Style Guidelines
- Keep helpers explicit and descriptive (snake_case), and annotate public
  functions with precise types.
- Avoid shell-specific shortcuts; prefer Python APIs and `pathlib.Path` helpers.
- Do not mutate archives or leave temporary files behind.

## Branch Workflow
- Always create a feature branch from `main` before making changes:
  - `git checkout -b feature-name`
  - Use descriptive names like `fix-zoom-bug` or `add-cbr-support`
- Push the feature branch to create a pull request
- After your PR is merged, update your local `main`:
  - `git checkout main`
  - `git pull`
  - Delete the merged branch: `git branch -d feature-name`

## Testing Guidelines
- Automated tests live in `tests/` and run with `python -m pytest` (or `make pytest`).
- When adding tests, keep `pytest` naming like `test_load_cbz_sorts_pages`.
- When using fakes, mirror the real `ComicViewer` interface rather than relaxing production code.
- Always use the `tk_root` fixture from `conftest.py` for Tkinter testing. Never manually create `tk.Tk()` instances with `root.withdraw()` and `root.update()` in tests as this causes timeouts in headless environments.
- For manual smoke tests, run `python cdisplayagain.py path/to/sample.cbz`, open both `.cbz` and `.cbr` samples, page through images, toggle fit/zoom, and ensure cleanup of temporary directories. Document any manual checklist you execute inside the pull request.

## Commit & Pull Request Guidelines
- Use imperative, component-scoped commit messages (e.g., "Add CBR extraction error copy")
- Bundle related changes per commit
- PR summary should describe user impact and testing performed
- Attach screenshots when UI is affected
- Pull requests should summarize user impact, list testing performed (commands and archive types opened), note any new dependencies (system packages like `unar`), and attach screenshots when UI is affected.

## Security & Configuration Tips
CBR support requires the external `unar` binary; verify contributors mention its installation path in reviews. Never check in sample comics or proprietary content—use small public-domain archives stored locally. When touching subprocess calls (`unar`, `rarfile`), sanitize user paths via `Path` helpers and prefer Python APIs over shell redirection.
