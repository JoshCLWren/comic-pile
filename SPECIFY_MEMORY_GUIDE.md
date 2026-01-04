# Using Specify Memory System - Comic Pile

## Overview

The Specify memory system has been populated with your existing documentation from:
- AGENTS.md
- MANAGER_DAEMON.md
- WORKFLOW_PATTERNS.md
- PRD summaries (from prd.md)
- Technical documentation (TECH_DEBT.md, ARCHITECTURE_TASK_API.md)
- API documentation (docs/API.md)
- 5 manager session retrospectives (manager1, manager2, manager3, manager6-postmortem, manager7)

## Memory Structure

All memory files are located in: `comic-pile/.specify/memory/`

### 1. constitution.md (280 lines)
Core principles, tech stack, development workflow, agent system principles, code quality standards, testing guidelines.

**When to read:**
- New developers joining the project
- Understanding project philosophy and constraints
- Clarifying coding standards and best practices
- Verifying compliance with project rules

**Key sections:**
- Core Principles (API-First, Minimal Dependencies, Mobile-First, Data Integrity, Clarity)
- Technology Stack (FastAPI, SQLite, HTMX, Tailwind, pytest, ruff, pyright)
- Development Workflow (build/test commands, branch strategy, git worktrees)
- Agent System Principles (Task API, active monitoring, delegation)
- Code Quality Standards (pre-commit hook, ruff configuration)
- Testing Guidelines (coverage requirements, test organization)
- Database Development
- Project Structure
- Product Philosophy
- Governance (amendment process, compliance verification)

### 2. agent-workflows.md (599 lines)
Proven patterns from successful sessions and critical failures from retrospectives.

**When to read:**
- Manager agents coordinating worker agents
- Understanding Task API usage and coordination workflows
- Learning from past mistakes (catastrophic failures)
- Worker agents understanding their workflow

**Key sections:**
- Successful Patterns (9 patterns with evidence from 4 successful sessions)
- Failed Patterns to Avoid (10 patterns with evidence from retrospectives)
- Manager Daemon Responsibilities (startup procedure, verification checklist)
- Worker Pool Manager Integration
- Task States and Transitions
- Worker Agent Workflow (standard workflow, responsibilities, anti-patterns)
- Manager Agent Workflow (standard workflow, responsibilities, anti-patterns)
- Key Lessons from Retrospectives (what works, what fails)

**Critical insights:**
- From Manager-6 (catastrophic failure): Systematic violation of proven patterns caused complete breakdown
- From Manager-7 (mixed success): Worker anti-patterns like "pre-existing issues" excuse
- 4 successful manager sessions (1, 2, 3, 7) proven patterns work when followed

### 3. prd-summary.md (556 lines)
Product requirements and design decisions from PRD.

**When to read:**
- Implementing new features
- Understanding product requirements
- Clarifying design decisions rationale
- Checking PRD alignment status

**Key sections:**
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

### 4. api-contracts.md (591 lines)
Key API endpoints and data contracts.

**When to read:**
- Developing API endpoints
- Writing API tests
- Understanding request/response schemas
- Debugging API integration issues

**Key sections:**
- API Overview (base URL, auth, documentation)
- Core Endpoints (Threads, Queue, Roll, Rate, Session)
- Task API (agent coordination endpoints)
- Admin (CSV import/export, JSON export)
- Data Models (ThreadResponse, RollResponse, SessionResponse, TaskResponse)
- Error Responses (400, 404, 409, 422)
- Usage Examples (curl commands)
- Testing Notes (httpx.AsyncClient usage)

### 5. technical-architecture.md (836 lines)
Architecture decisions, tech debt, and proven solutions.

**When to read:**
- Understanding system architecture
- Evaluating technical decisions
- Reviewing technical debt items
- Planning refactoring or scaling

**Key sections:**
- Architecture Overview (monolithic FastAPI, separation of concerns)
- Key Design Decisions (monolithic, SQLite, API-first, Task API)
- Technology Stack (backend, database, ORM, testing, code quality)
- Database Schema (threads, sessions, events, users, tasks)
- Key Components (dice ladder, queue management, session detection, caching)
- Technical Debt (26 items categorized by priority)
  - Critical: 1 (d10 rendering)
  - High: 6 (hardcoded tasks, import errors, no transactions, missing implementations)
  - Medium: 10 (cache, user_id=1, CORS, session logic)
  - Low: 9 (auth, logging, coverage, migrations, jobs, versioning)
- Known Issues (d10 rendering history and approaches)
- Deployment (development, SQLite production, PostgreSQL production)
- Performance (caching, database queries, frontend)
- Security Considerations (current model, recommendations)
- Monitoring and Logging (current state, recommendations)
- Scalability Considerations (current limitations, when to scale, scaling options)
- Architecture Decisions Rationale (why monolithic, why SQLite, why HTMX, why Tailwind)
- Proven Solutions (6 successful resolutions with evidence)
  - Integration test database isolation
  - Uvicorn version pinning
  - Merge conflict resolution with `git checkout --theirs --ours`
  - Python 3.13 compatibility verification
  - Performance optimization O(n) to O(1)
  - Playwright integration testing

### 6. testing-quality-guide.md (624 lines)
Testing strategies, linting, and code quality standards.

**When to read:**
- Writing tests
- Running linting
- Understanding code quality standards
- Fixing test failures or linting errors

**Key sections:**
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

### 7. memory-index.md (556 lines)
Navigation guide and quick reference for all memory files.

**When to read:**
- Quick reference for all memory files
- Finding the right memory file for your current context
- Understanding success metrics and catastrophic failures

**Key sections:**
- Memory Files Overview (quick description of each file)
- Quick Navigation (when to read each file)
- Key Numbers Reference (product, agent system, technical)
- Common Workflows (starting development, creating feature branch, fixing a bug, agent coordination)
- Troubleshooting (tests failing, linting errors, pre-commit hook, agent issues, database issues)
- Related Documentation (links to project files, agent system docs, retrospectives)
- Version History (updates to memory system)

**Success Metrics (from retrospectives):**
- Delegation compliance: 100% of work via Task API
- Active monitoring: Polling loop running within 5 minutes of worker launch
- Blocked task resolution: All blocked tasks addressed within 10 minutes of detection
- Worktree availability: <5% of in_review tasks with missing worktrees
- Merge success rate: >80% of in_review tasks successfully merged

**Catastrophic Failures (from Manager-6):**
- Direct investigation instead of delegation
- No active monitoring implemented
- Workers removing worktrees before merge
- Test coverage blocking all work with 96% threshold
- Manager daemon ineffective and silent
- Merge conflicts left unresolved
- Cognitive degradation

## How to Use with Specify Commands

The memory files are configured to be used by these Specify commands:

### /speckit.constitution
Reads and updates `.specify/memory/constitution.md` based on user input.

### /speckit.analyze
Analyzes consistency across spec.md, plan.md, and tasks.md.
- Reads from memory files for context
- Reports inconsistencies and quality issues

### /speckit.plan
Breaks plan into tasks and generates design artifacts.
- Reads from all memory files for comprehensive context
- Generates research.md, data-model.md, contracts/, quickstart.md

### /speckit.tasks
Generates tasks.md from plan, spec, and other artifacts.
- Reads from memory files for agent workflows and technical context
- Maps requirements and stories to tasks

## Quick Reference Tables

### Key Numbers

**Product:**
- Session gap: 6 hours
- Dice ladder: d4, d6, d8, d10, d12, d20
- Rating scale: 0.5 to 5.0 (step 0.5)
- Queue movement threshold: 4.0 (≥ front, < back)
- Coverage requirement: 96%

**Agent System:**
- Heartbeat interval: 5-10 minutes
- Stale task threshold: 20+ minutes no heartbeat
- Maximum concurrent workers: 3
- Maximum worktrees: 3 (WIP limit)

**Technical:**
- Python version: 3.13
- Cache TTL: 30s (threads), 10s (sessions)
- Line length: 100 characters

### Common Workflows

**Starting Development:**
```bash
source .venv/bin/activate
uv sync --all-extras
make migrate
make seed
make dev
```

**Agent Coordination:**
```bash
# Verify daemon
ps aux | grep manager_daemon
tail -20 logs/manager-$(date +%Y%m%d).log
curl http://localhost:8000/api/tasks/reviewable

# Create worktrees
git worktree add ../comic-pile-p2 phase/2-database-models

# Launch workers
# (Use Worker Pool Manager or manual workers)

# Monitor actively
# (Set up 2-5 minute polling loop)
```

## Proven Patterns Summary

From 4 successful manager sessions and 1 catastrophic failure:

**What Works:**
- Task API dependency checking is robust
- 409 Conflict prevents duplicate claims
- `/ready` endpoint returns only tasks with satisfied dependencies
- Clear review feedback leads to successful fixes
- Merge conflicts resolved with `git checkout --theirs --ours`
- Fact-checking before claiming incompatibility saves time
- Active monitoring enables quick response to issues

**What Fails (from Manager-6 catastrophic failure):**
- Direct investigation instead of delegation
- No active monitoring implemented
- Workers removing worktrees before merge
- Rigid 96% coverage requirement blocking work
- Manager daemon ineffective and silent
- Merge conflicts left unresolved
- Cognitive degradation

## Related Documentation

**Project Files:**
- AGENTS.md - Repository guidelines and workflow patterns
- MANAGER_DAEMON.md - Manager daemon setup and integration
- WORKFLOW_PATTERNS.md - Proven successful patterns from sessions
- README.md - Quick start and project overview
- TECH_DEBT.md - Detailed technical debt items
- ARCHITECTURE_TASK_API.md - Task API extraction analysis
- PRD_MISSES.md - PRD compliance gap analysis
- docs/API.md - Full API documentation
- CONTRIBUTING.md - Contributing guidelines

**Agent System:**
- MANAGER-7-PROMPT.md - Manager agent coordination prompt
- worker-pool-manager-prompt.txt - Worker Pool Manager agent prompt

**Retrospectives:**
- retro/manager1.md - Successful PRD alignment session
- retro/manager2.md - Successful tech debt cleanup session
- retro/manager3.md - Successful PRD alignment and optimization session
- retro/manager6-postmortem.md - Catastrophic failure analysis
- retro/manager7.md - Mixed success session (workers marking in_review without fixing tests)

## Memory Updates

Memory files should be updated when:
- New core principles are established
- New proven patterns are discovered from retrospectives
- New product requirements are added or changed
- API contracts change
- Architecture decisions are made
- Technical debt items are resolved
- New quality standards are introduced
- Retrospectives identify new patterns

Update version history in `memory-index.md` and increment constitution version if governance changes.

## Total Memory Coverage

- Constitution: Core principles and governance
- Agent Workflows: 10 successful patterns + 10 failed patterns + manager daemon + worker/manager workflows + retrospective lessons
- PRD Summary: Product requirements and design decisions
- API Contracts: All endpoints, models, and usage examples
- Technical Architecture: 26 tech debt items + 6 proven solutions + deployment options
- Testing Guide: Testing strategies, linting, and code quality
- Memory Index: Navigation and quick reference

**Total:** 3,985 lines of comprehensive documentation covering all aspects of Comic Pile development.
