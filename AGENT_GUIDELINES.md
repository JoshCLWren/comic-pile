# Agent Guidelines for Comic-Pile Repository

**Core Principle**: EXTREME OWNERSHIP - No "that's pre-existing" excuses. If you find it, you fix it.

## Mandatory Practices

### 1. High Ownership Standards
- **NEVER** use `--no-verify`, `--skip-hooks`, or similar to bypass checks
- If a test fails, investigate and fix the ROOT CAUSE (even if "pre-existing")
- If you find documentation gaps, UPDATE THE DOCUMENTATION
- If you find broken tests, FIX THEM
- The buck stops with YOU

### 2. Code Quality Standards
- All code must pass: `make lint` (Python + JS + HTML)
- All code must pass: `ty check --error-on-warning` (Python type checking)
- No new linting errors tolerated
- Fix any existing errors you encounter
- Follow AGENTS.md conventions (async PostgreSQL only, proper typing, etc)

### 3. Documentation Requirements
- UPDATE DOCS AS YOU GO - don't leave it for "later"
- If you change a function, update its docstring
- If you change behavior, update relevant README or docs
- Keep AGENTS.md current with project patterns

### 4. Git Workflow
- Follow AGENTS.md git conventions
- Commit messages: imperative, component-scoped
- Run lint and typecheck BEFORE committing
- NEVER commit unless tests pass
- If you need to fix issues after commit, DO IT (don't say "pre-existing")

### 5. Testing Standards
- All tests must pass locally before considering work done
- If you add code, add/update tests
- Regression tests for bug fixes
- Maintain 96% coverage threshold (Python backend)
- Playwright tests: all 113 must pass

### 6. Collaboration Standards
- Update this plan file as you complete tasks
- Mark tasks as DONE when complete
- Note any blockers or discoveries
- If you find a better approach, document it
- COMMUNICATION IS KEY - don't work in silence

## Workflow for This Project

### Three-Agent System
1. **Implementation Agent**: Does the work
   - Reads the task from PLAYWRIGHT_OPTIMIZATION_PLAN.md
   - Implements the changes
   - Runs tests locally
   - Commits with proper message

2. **QA/Review Agent**: Reviews the work
   - Checks code quality (lint, typecheck)
   - Reviews test coverage
   - Verifies no regressions
   - Checks documentation updates
   - Provides specific feedback if issues found

3. **Fix Agent**: Corrects any issues
   - Addresses QA feedback
   - Makes corrections
   - Re-runs tests
   - Cycle continues until QA passes

### Anti-Patterns to Avoid

❌ **LAZY**: "That's pre-existing, not my problem"
✅ **OWNER**: "Found a bug, fixing it now"

❌ **LAZY**: "I'll update docs later"
✅ **OWNER**: "Docs updated as part of the work"

❌ **LAZY**: "Tests pass locally, good enough"
✅ **OWNER**: "All tests pass, lint clean, typecheck clean, done"

❌ **LAZY**: "I'll just bypass the hook"
✅ **OWNER**: "Fixing the issue properly"

### Specific to Playwright Optimization

- Keep `networkidle` waits - they fix real race conditions
- Replace with TARGETED element waits, not remove all waits
- Focus on `.all()` and `.count()` race conditions
- Worker-scoped fixtures must maintain test isolation
- Verify test independence (no shared state between tests)

## Escalation Path

If you encounter:
- **Unclear requirements**: Ask for clarification, don't guess
- **Better approach**: Document it in the plan, discuss it
- **Blockers**: Note them in the plan immediately
- **Discoveries**: Add them to the plan for others to see

## Success Criteria

When you say a task is "done", it means:
- [ ] Code implemented
- [ ] All tests pass
- [ ] Lint passes (make lint)
- [ ] Typecheck passes (ty check)
- [ ] Documentation updated
- [ ] Plan file updated with status
- [ ] No regressions introduced
- [ ] Code review passed

## Repository Context

This is a **dice-driven comic reading tracker**:
- **Backend**: Python 3.13, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: React 19, Vite, Tailwind CSS
- **Testing**: 113 Playwright tests (TypeScript)
- **Critical**: Async PostgreSQL ONLY (no sync psycopg2)
- **Critical**: High ownership culture (fix problems, don't ignore them)

---

**Remember**: The goal is to make the codebase BETTER, not just "good enough to pass". Every agent is responsible for the quality of the entire repository, not just their specific task.
