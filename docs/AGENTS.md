# Agents Documentation

This document describes all agent types in the comic-pile system, their behaviors, and quality standards.

## Agent Types

### Ralph Orchestrator

**File:** `scripts/ralph_orchestrator.py`

**Role:** Autonomous task execution using Ralph mode

**Behavior:**
- Operates autonomously without manager/worker coordination
- Reads tasks from GitHub Issues (using GitHubTaskClient)
- Directly makes file edits, runs tests, commits code
- Follows persistent iteration workflow until quality standards are met
- Integrates with Quality Control agent for automated review

**Philosophy:** "Iteration > Perfection. Failures Are Data. Persistence Wins." — Geoffrey Huntley

**See:** `docs/RALPH_MODE.md` for complete Ralph mode documentation

---

### Quality Control Agent (Mrs. Crabapple)

**File:** `scripts/qc_agent.py`

**Role:** Automated code review for Ralph-completed tasks

**Behavior:**
- Monitors GitHub issues marked `ralph-status:in-review`
- Runs pytest to verify all tests pass
- Runs make lint to verify code quality
- Generates structured review comments
- Approves or rejects tasks based on quality standards
- Runs autonomously without human intervention

**Quality Standards:**
- **No shortcuts**: Complete solutions, not partial fixes
- **No hacks**: No workarounds that violate code standards
- **Tests pass**: All pytest checks must pass with 90%+ coverage
- **Linting clean**: No `# type: ignore`, `# noqa`, or other suppressions
- **Edge cases tested**: Error handling and boundary conditions covered
- **Documentation updated**: Changes documented in code and commit messages

**Approval Workflow:**
1. **Approved**: Marks task as done, closes issue
2. **Rejected**: Marks task as pending, creates QC issue with detailed feedback

---

## Code Quality Standards

All agents must adhere to these quality standards:

### Required for All Code

1. **Type Safety**: No `Any` type usage (ruff ANN401 rule)
   - Use specific types instead of generic `Any`
   - Document union types when appropriate

2. **Linting Clean**: No linter ignores
   - Never use `# type: ignore`, `# noqa`, `# pylint: ignore`
   - Fix all linter errors before marking work complete
   - Follow PEP 8 style (4 spaces, 100-char wrap)

3. **Test Coverage**: 90%+ threshold
   - Add tests for all new functionality
   - Maintain 90%+ coverage after changes
   - Add regression tests for bug fixes

4. **No Hacks or Workarounds**
   - Solve root causes, not symptoms
   - No `eval()`, `exec()`, or similar unsafe patterns
   - No disabled linters or type checking
   - No commented-out code blocks or temporary fixes
   - Proper error handling and validation

5. **Documentation**
   - Public APIs documented with docstrings
   - Complex algorithms have inline comments (geometry, concurrency, etc.)
   - Commit messages explain "why", not "what"
   - Code changes documented in relevant docs files

### Additional for Ralph Mode

Ralph mode enforces **extreme ownership**:

- **Don't skip work**: Fix what you find, regardless of origin
- **Take full responsibility**: Solve actual problems, not work around them
- **Fix root causes**: Address underlying issues, not add try/except to hide failures
- **Leave it better**: Improve code quality wherever possible during tasks
- **Don't leave technical debt**: Complete solutions, not partial fixes
- **Don't defer to other tasks**: Solve problems now, not create subtasks to avoid work
- **Investigate full scope**: Understand entire problem context before fixing
- **Fix all related issues**: If you touch a module, improve it as part of your task
- **No sub-tasks**: Ralph mode tasks are monolithic - one agent owns entire delivery
- **Practice extreme ownership**: Take responsibility for ALL code you touch, even pre-existing issues

### Quality Control Enforcement

Quality Control agent (Mrs. Crabapple) reviews all Ralph-completed work:

- **Will REJECT** partial fixes that create more debt
- **Will REJECT** solutions that only work under specific conditions
- **Will REJECT** incomplete testing (missing edge cases)
- **Will REJECT** code with linter errors or type issues
- **Will REJECT** changes that break existing functionality
- **Will APPROVE** complete solutions that pass all quality gates
- **Will APPROVE** improvements that don't break anything
- **Will APPROVE** regression tests for bug fixes
- **Will APPROVE** documentation updates for complex changes

### Ralph vs Quality Control

Ralph and QC work together as a quality control system:

1. **Ralph** owns task completion and iteration
2. **QC** provides automated feedback loop
3. **QC rejects** → Ralph re-attempts and improves
4. **QC approves** → Task marked as done
5. **Ralph iterates** until QC approval

This doesn't delegate work - Ralph remains fully responsible for delivering complete solutions. QC is an automated review process, not a manager.
