# Memory Index - Comic Pile

This document provides an index and quick reference for all Specify memory files in Comic Pile.

---

## Memory Files

### 1. constitution.md
**Purpose:** Core principles, tech stack, and development standards for Comic Pile.
**When to Read:**
- New developers joining the project
- Understanding project philosophy and constraints
- Clarifying coding standards and best practices
- Verifying compliance with project rules

**Key Sections:**
- Core Principles (API-First, Minimal Dependencies, Mobile-First, Data Integrity, Clarity)
- Technology Stack (FastAPI, SQLite, HTMX, Tailwind, etc.)
- Development Workflow (branch strategy, git worktrees, build/test commands)
- Agent System Principles (Task API, active monitoring, delegation)
- Code Quality Standards (pre-commit hook, ruff configuration)
- Testing Guidelines (coverage requirements, test organization)
- Database Development (models, Alembic, service layer)
- Project Structure
- Product Philosophy (reading threads, dice ladder, queue, sessions)
- Governance (amendment process, compliance verification)

**Quick Reference:**
- Coverage requirement: 96%
- Session gap: 6 hours
- Dice ladder: d4 → d6 → d8 → d10 → d12 → d20
- Rating scale: 0.5 → 5.0 (step 0.5)
- Queue movement: ≥4.0 → front, <4.0 → back

---

### 2. agent-workflows.md
**Purpose:** Proven patterns and critical failures from agent sessions, with detailed workflow guidance.
**When to Read:**
- Manager agent coordinating worker agents
- Understanding Task API usage
- Debugging agent coordination issues
- Learning from past manager session retrospectives
- Understanding proven patterns and catastrophic failures

**Key Sections:**
- Successful Patterns (9 patterns with evidence)
  - Always use Task API for all work
  - Trust Task API state
  - Active monitoring (not passive claims)
  - Delegate immediately, never investigate yourself
  - Worker reliability management
  - Worktree management
  - Manager daemon integration
  - Merge conflict handling
  - Browser testing delegation
- Failed Patterns to Avoid (4 patterns)
  - NO active monitoring
  - Direct file edits before delegation
  - Worker Pool Manager role violation
  - Ad-hoc worktree creation
- Manager Daemon Responsibilities
  - What daemon does (automated)
  - What manager still must do
  - Startup procedure and verification checklist
- Worker Pool Manager Integration
- Task States and Transitions
- Worker Agent Workflow (standard workflow, responsibilities, anti-patterns)
- Manager Agent Workflow (standard workflow, responsibilities, anti-patterns)

**Quick Reference:**
- Heartbeat interval: 5-10 minutes
- Stale task threshold: 20+ minutes no heartbeat
- Maximum concurrent workers: 3
- Task states: pending → in_progress → blocked/in_review → done
- Worktree lifecycle: Create at session start, keep until task done, then remove
- Manager daemon verification: ps aux | grep manager_daemon, check logs, verify /api/tasks/reviewable

**Success Metrics:**
- Delegation compliance: 100% of work via Task API
- Active monitoring: Polling loop running within 5 minutes of worker launch
- Blocked task resolution: All blocked tasks addressed within 10 minutes
- Worktree availability: <5% of in_review tasks with missing worktrees
- Merge success rate: >80% of in_review tasks successfully merged

**Catastrophic Failures to Avoid:**
- Direct investigation instead of delegation (Manager-6)
- No active monitoring implemented (Manager-6)
- Workers removing worktrees before merge (Manager-6)
- Test coverage blocking all work with 96% threshold (Manager-6)
- Manager daemon ineffective and silent (Manager-6)
- Merge conflicts left unresolved (Manager-6)
- Workers marking in_review without fixing tests/linting (Manager-7)

**Proven Patterns (from 4 successful sessions):**
- Task API dependency checking works correctly
- `/ready` endpoint prevents claiming tasks with unmet dependencies
- Merge conflicts resolved with `git checkout --theirs --ours`
- Workers follow claim-before-work workflow
- Clear, actionable review feedback with specific issues and line numbers

---

### 3. prd-summary.md
**Purpose:** Product requirements and design decisions from PRD, providing essential context for development decisions.
**When to Read:**
- Implementing new features
- Understanding product requirements
- Clarifying design decisions rationale
- Checking PRD alignment status

**Key Sections:**
- Core Philosophy (support existing ritual, not gamify)
- Core Concepts (reading thread, queue, dice ladder)
- Session Model (boundary, scope, pending reads)
- Roll Behavior (roll pool, manual override)
- Rating Model (scale, progress rules, queue movement)
- Completion Semantics
- Staleness Awareness
- Time Tracking
- Reviews & External Data
- Export Policy
- Narrative Session Summary
- Data Model (JSON v1)
- Wireframes (roll screen, rate screen, queue screen)
- PRD Alignment Status (~90% complete)
- Key Implementation Notes
- Design Decisions Rationale
- Future Enhancements (not in PRD)

**Quick Reference:**
- Philosophy: Support existing ritual, chaos allowed
- Dice: Sacred, ladder self-corrects
- Notes: No notes system in app (use League of Comic Geeks)
- Session: Time-based (6 hours), no manual button
- Rating: 0.5-5.0 scale, encodes intent via queue movement

---

### 4. api-contracts.md
**Purpose:** Key API endpoints and data contracts for Comic Pile, providing essential context for API development and testing.
**When to Read:**
- Developing API endpoints
- Writing API tests
- Understanding request/response schemas
- Debugging API integration issues

**Key Sections:**
- API Overview (base URL, auth, documentation)
- Core Endpoints (Threads, Queue, Roll, Rate, Session)
- Task API (agent coordination endpoints)
- Admin (CSV import/export, JSON export)
- Data Models (ThreadResponse, RollResponse, SessionResponse, TaskResponse)
- Error Responses (400, 404, 409, 422)
- Usage Examples (curl commands)
- Notes (single-user, session timeout, dice ladder, caching, CORS)
- Testing Notes (httpx.AsyncClient usage)

**Quick Reference:**
- Base URL: http://localhost:8000
- Auth: None (single-user)
- Docs: http://localhost:8000/docs (Swagger), /redoc (ReDoc)
- Content-Type: application/json

**Common Endpoints:**
- POST /roll/ - Roll dice
- POST /rate/ - Rate reading
- GET /threads/ - List threads
- POST /api/tasks/{id}/claim - Claim task (agents)
- GET /api/tasks/ready - Get ready tasks (agents)

---

### 5. technical-architecture.md
**Purpose:** Key architectural decisions, tech debt, and technical context for Comic Pile.
**When to Read:**
- Understanding system architecture
- Evaluating technical decisions
- Reviewing technical debt
- Planning refactoring or scaling

**Key Sections:**
- Architecture Overview (monolithic FastAPI, separation of concerns)
- Key Design Decisions (monolithic, SQLite, API-first, Task API)
- Technology Stack (backend, database, ORM, testing, code quality)
- Database Schema (threads, sessions, events, users, tasks)
- Key Components (dice ladder, queue management, session detection, caching)
- Technical Debt (26 items, categorized by priority)
  - Critical: d10 rendering
  - High: hardcoded tasks, import errors, no transactions
  - Medium: cache invalidation, user_id=1, CORS, session logic
  - Low: auth, logging, coverage, migrations, jobs, versioning
- Known Issues (d10 rendering history and approaches)
- Deployment (development, SQLite production, PostgreSQL production)
- Performance (caching, database queries, frontend)
- Security Considerations (current model, recommendations)
- Monitoring and Logging (current state, recommendations)
- Scalability Considerations (current limitations, when to scale, scaling options)
- Architecture Decisions Rationale (why monolithic, why SQLite, why HTMX, why Tailwind)
- Future Architecture Considerations (multi-user, native mobile, Task API extraction)

**Quick Reference:**
- Architecture: Monolithic FastAPI
- Database: SQLite (dev), PostgreSQL (prod option)
- ORM: SQLAlchemy 2.0
- Caching: In-memory dict (30s threads, 10s sessions)
- Testing: pytest + httpx.AsyncClient
- Coverage: 96%

**Technical Debt Summary:**
- Total: 26 items
- Critical: 1 (d10 rendering)
- High: 6
- Medium: 10
- Low: 9
- Estimated effort: 60-100 hours

---

### 6. testing-quality-guide.md
**Purpose:** Essential guidance for testing, linting, and maintaining code quality in Comic Pile.
**When to Read:**
- Writing tests
- Running linting
- Understanding code quality standards
- Fixing test failures or linting errors

**Key Sections:**
- Testing (running tests, coverage requirements, strategies, organization, fixtures, naming, structure)
- Async vs Sync Tests
- Integration Tests
- Regression Tests
- Linting (running, lint script, pre-commit hook, manual testing)
- Ruff Configuration (rules, common errors)
- Pyright Configuration (common errors)
- Code Style Guidelines (naming, imports, type hints, docstrings)
- Common Anti-Patterns to Avoid (5 patterns)
- Continuous Integration (CI configuration, CI checks, running locally)
- Quality Checklist (testing, linting, code quality, best practices)
- Debugging Tests (verbose, stopping, debugging, isolation)
- Resources (documentation links, project docs, make commands)

**Quick Reference:**
- Run tests: `pytest` or `make pytest`
- Run linting: `make lint` or `bash scripts/lint.sh`
- Coverage: 96% minimum
- Pre-commit hook: Blocks commits with `# type: ignore`, `# noqa`, etc.

**Make Commands:**
- `make dev` - Run development server
- `make pytest` - Run tests with coverage
- `make lint` - Run ruff and pyright
- `make seed` - Seed database
- `make migrate` - Run migrations
- `make githook` - Test pre-commit hook

---

## Quick Navigation

### I'm a New Developer

Start here:
1. **constitution.md** - Understand project philosophy and coding standards
2. **testing-quality-guide.md** - Learn how to run tests and maintain quality
3. **prd-summary.md** - Understand product requirements

### I'm Implementing a Feature

Read in order:
1. **prd-summary.md** - Understand requirements
2. **api-contracts.md** - See existing endpoints and models
3. **technical-architecture.md** - Understand architecture context
4. **testing-quality-guide.md** - Write tests
5. **constitution.md** - Verify compliance

### I'm a Manager Agent

Read in order:
1. **agent-workflows.md** - Learn proven patterns and workflows
2. **constitution.md** (Agent System Principles section) - Understand your role
3. **api-contracts.md** (Task API section) - Learn Task API usage
4. **technical-architecture.md** (Technical Debt section) - Avoid known issues

### I'm a Worker Agent

Read in order:
1. **agent-workflows.md** (Worker Agent Workflow, Worker Anti-Patterns) - Learn your workflow and anti-patterns to avoid
2. **api-contracts.md** (Task API section) - Learn Task API usage
3. **constitution.md** (Code Quality Standards) - Follow coding standards
4. **testing-quality-guide.md** - Write tests for your changes

**Critical Reminders:**
- Fix all test failures before marking in_review
- Fix all linting errors before marking in_review
- Keep worktree until task is merged (status becomes 'done')
- Never claim incompatibility without fact-checking
- Never mark tasks in_review with "pre-existing issues" - fix them instead

### I'm Debugging an Issue

Read:
1. **technical-architecture.md** (Known Issues, Technical Debt) - Check if issue is documented
2. **testing-quality-guide.md** (Debugging Tests) - Learn debugging techniques
3. **api-contracts.md** (Error Responses) - Understand error codes
4. **agent-workflows.md** (Failed Patterns) - Check if you're making a known mistake (10 failed patterns documented)

**Critical Errors:**
- Direct file edits before delegating → Stop, create task instead
- Not monitoring actively → Set up polling loop immediately
- Workers removing worktrees before merge → Verify worktree exists before merge
- Marking tasks in_review with failing tests → Fix all tests first
- Ignoring blocked tasks → Address within 5-10 minutes

### I'm Planning Architecture Changes

Read:
1. **technical-architecture.md** - Understand current architecture and rationale
2. **constitution.md** (Governance section) - Follow amendment process
3. **prd-summary.md** (Design Decisions Rationale) - Understand design philosophy

### I'm Reviewing a PR

Check:
1. **constitution.md** - Verify coding standards compliance
2. **testing-quality-guide.md** (Quality Checklist) - Verify tests and quality
3. **technical-architecture.md** (Technical Debt) - Ensure no new debt introduced

---

## Key Numbers Reference

### Product
- Session gap: 6 hours
- Dice ladder: d4, d6, d8, d10, d12, d20
- Rating scale: 0.5 to 5.0 (step 0.5)
- Queue movement threshold: 4.0 (≥ front, < back)
- Coverage requirement: 96%

### Agent System
- Heartbeat interval: 5-10 minutes
- Stale task threshold: 20 minutes
- Maximum concurrent workers: 3
- Maximum worktrees: 3 (WIP limit)

### Technical
- Python version: 3.13
- Cache TTL: 30s (threads), 10s (sessions)
- Line length: 100 characters
- Session timeout: 6 hours

---

## Common Workflows

### Starting Development

```bash
# 1. Activate environment
source .venv/bin/activate

# 2. Install dependencies (if needed)
uv sync --all-extras

# 3. Run migrations
make migrate

# 4. Seed database (optional)
make seed

# 5. Run tests
pytest

# 6. Run linting
make lint

# 7. Start dev server
make dev
```

### Creating a Feature Branch

```bash
# 1. Start from main
git checkout main
git pull origin main

# 2. Create branch
git checkout -b phase/feature-name

# 3. Create worktree (if agent work)
git worktree add ../comic-pile-p2 phase/feature-name
```

### Fixing a Bug

```bash
# 1. Run tests to see failure
pytest

# 2. Investigate and fix issue
# (Read technical-architecture.md for context if needed)

# 3. Write regression test
# (See testing-quality-guide.md)

# 4. Run tests to verify fix
pytest

# 5. Run linting
make lint

# 6. Commit and push
git add .
git commit -m "fix: description"
git push
```

### Agent Coordinating Work

```bash
# 1. Verify daemon is running
ps aux | grep manager_daemon

# 2. Check task status
curl http://localhost:8000/api/tasks/coordinator-data

# 3. Create worktrees
git worktree add ../comic-pile-p1 phase/1-feature
git worktree add ../comic-pile-p2 phase/2-feature

# 4. Launch workers
# (Use Worker Pool Manager or manual workers)

# 5. Monitor actively
# (Set up 2-5 minute polling loop)
```

---

## Troubleshooting

### Tests Failing

1. Run with verbose output: `pytest -v`
2. Check specific test: `pytest tests/test_file.py::test_function`
3. Run with debugger: `pytest --pdb`
4. Check coverage: `pytest --cov=comic_pile --cov-report=term-missing`

### Linting Errors

1. Run ruff only: `ruff check .`
2. Fix auto-fixable: `ruff check --fix .`
3. Format code: `ruff format .`
4. Run pyright: `pyright .`
5. Check rules in constitution.md (Code Quality Standards)

### Pre-commit Hook Blocking

1. See what's blocking: `bash scripts/lint.sh`
2. Fix issues found by lint script
3. Remove `# type: ignore`, `# noqa`, etc. from code
4. Add proper type hints instead of `Any`
5. Test hook manually: `make githook`

### Agent Issues

1. Check daemon is running: `ps aux | grep manager_daemon`
2. Check daemon logs: `tail -f logs/manager-$(date +%Y%m%d).log`
3. Check task status: `curl http://localhost:8000/api/tasks/coordinator-data`
4. Review agent-workflows.md for proven patterns
5. Check worktree exists: `git worktree list`

### Database Issues

1. Run migrations: `make migrate`
2. Check schema in models: `app/models/*.py`
3. Check migrations: `alembic/versions/*.py`
4. Seed data (if needed): `make seed`
5. Backup data: `curl http://localhost:8000/admin/export/json/ > backup.json`

---

## Related Documentation

### Project Files
- **AGENTS.md** - Repository guidelines and workflow patterns
- **MANAGER_DAEMON.md** - Manager daemon setup and integration
- **WORKFLOW_PATTERNS.md** - Proven successful patterns from sessions
- **README.md** - Quick start and project overview
- **TECH_DEBT.md** - Detailed technical debt items
- **ARCHITECTURE_TASK_API.md** - Task API extraction analysis
- **PRD_MISSES.md** - PRD compliance gap analysis
- **docs/API.md** - Full API documentation
- **CONTRIBUTING.md** - Contributing guidelines

### Agent System
- **MANAGER-7-PROMPT.md** - Manager agent coordination prompt
- **worker-pool-manager-prompt.txt** - Worker Pool Manager agent prompt
- **AGENT_P1_WT2.md, AGENT_P1_WT3.md, etc.** - Phase 1 work task assignments

### Retrospectives
- **retro/manager1.md, manager2.md, manager3.md, etc.** - Manager session retrospectives
- **retro/manager6-postmortem.md** - Critical failure analysis

---

## Memory Update Guidelines

### When to Update Memory Files

Update these memory files when:
- New core principles are established (constitution.md)
- New proven patterns are discovered (agent-workflows.md)
- New product requirements are added (prd-summary.md)
- API contracts change (api-contracts.md)
- Architecture decisions are made (technical-architecture.md)
- New quality standards are introduced (testing-quality-guide.md)

### How to Update

1. Identify which memory file needs updating
2. Read current content to understand structure
3. Add or modify sections with clear rationale
4. Update "Last Amended" date in constitution.md if governance changes
5. Commit with clear message: `docs: update [memory-file] for [reason]`
6. Update this index file if new memory files are added

### Governance

- Constitution amendments require approval via pull request
- Technical debt items should be resolved and documented in commit
- New proven patterns should be backed by evidence from retrospectives
- API contracts should match actual implementation (test-driven)
- Architecture decisions should reference retrospective analysis

---

## Version History

- **v1.1.0** (2026-01-03) - Enhanced with retrospective insights
  - Updated agent-workflows.md with 3 additional failed patterns (total 10)
  - Added 3 additional success patterns (merge conflict resolution, fact-checking, clear review feedback)
  - Enhanced memory-index.md with success metrics, catastrophic failures, and critical errors
  - Added proven patterns from 4 successful manager sessions
  - Added catastrophic failure analysis from manager-6 postmortem

- **v1.0.0** (2026-01-03) - Initial memory system created
  - constitution.md - Core principles and standards
  - agent-workflows.md - Proven patterns from sessions
  - prd-summary.md - Product requirements
  - api-contracts.md - API endpoints and models
  - technical-architecture.md - Architecture and tech debt
  - testing-quality-guide.md - Testing and quality guide
  - memory-index.md (this file) - Navigation and quick reference
