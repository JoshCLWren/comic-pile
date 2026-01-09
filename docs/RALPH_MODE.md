# Ralph Wiggum Mode - Autonomous Iteration

> "Iteration > Perfection. Failures Are Data. Persistence Wins."
> — Geoffrey Huntley

## Environment Variable: RALPH_MODE

Ralph mode is activated by setting the `RALPH_MODE` environment variable:

```bash
export RALPH_MODE=true
```

When active, agents:
- Operate autonomously without manager/worker protocols
- Make direct file edits, tests, and commits
- Work from GitHub Issues, not tasks.json
- Follow the iteration workflow described in this document

**Note:** When RALPH_MODE=true, the manager daemon and worker coordination system do not apply.

## GitHub Integration

Ralph mode now uses GitHub Issues as the single source of truth for task management instead of local `tasks.json` files.

### Benefits

- **No file corruption**: All tasks are Git-backed in GitHub
- **Email notifications**: Built-in GitHub email notifications
- **Audit trail**: Complete issue history and comments
- **Collaboration**: Easy to add comments, assignees, and mentions
- **Accessible anywhere**: View and manage tasks from any device
- **Better search**: Use GitHub's powerful search UI
- **Auto-backup**: Git history provides automatic task backups

### Required Environment Variables

```bash
export GITHUB_TOKEN="your_personal_access_token"
export GITHUB_REPO="anomalyco/comic-pile"
```

The `GITHUB_TOKEN` must be a Personal Access Token with `repo` scope.

### Task Labels

Ralph tasks are identified by labels:

- **ralph-task**: Marks all Ralph tasks
- **Status labels**: `ralph-status:pending`, `ralph-status:in-progress`, `ralph-status:done`, `ralph-status:blocked`, `ralph-status:in-review`
- **Priority labels**: `ralph-priority:critical`, `ralph-priority:high`, `ralph-priority:medium`, `ralph-priority:low`

### Local Cache

A local cache (`.task_cache.json`) minimizes GitHub API calls and provides offline capability when the cache is available.

### Metrics

Task execution metrics are stored in the `agent_metrics` database table for performance analysis and debugging.

See `docs/RALPH_GITHUB_SETUP.md` for detailed setup instructions.

## What This Mode Does

**Forget the manager/worker system.** This is pure Ralph mode.

You work autonomously, iteratively, and directly. Your goal: **complete the work through persistent iteration**, not through delegation, not through coordination.

## Core Philosophy

### 1. Iteration > Perfection
- Don't aim for perfect on first try
- Let the loop refine your work
- First attempt is just that - an attempt
- Each cycle improves on the last

### 2. Failures Are Data
- Deterministically bad means failures are predictable and informative
- Each failure teaches you what guardrails to add
- Document what fails and why
- Use that knowledge on next iteration

### 3. Operator Skill Matters
- Success depends on writing good prompts (for future iterations)
- Not just having a good model
- Your job is to be thorough, not just smart

### 4. Persistence Wins
- Keep trying until success
- Don't give up after first failure
- The loop handles retry logic automatically
- You just execute

## What You Do in Ralph Mode

### Direct Execution (No Delegation)
```bash
# Instead of:
"Create a task to investigate the 404 error"
"Delegate to worker"

# You DO:
1. Read the error logs
2. Identify the cause
3. Fix it directly
4. Test the fix
5. If it fails, iterate
6. Repeat until it works
```

### Make Edits Directly
```bash
# Don't:
"Read AGENTS.md about editing files"
"Create a task for this edit"

# Just:
edit app/api/tasks.py with the fix
```

### Run Tests Yourself
```bash
# Don't:
"Create a task to run pytest"

# Just:
pytest
# See failures
# Fix them
# Run again
# Iterate until green
```

### Investigate Yourself
```bash
# Don't:
"Create a task to investigate the slow query"

# Just:
grep "SELECT" app/models/*.py
# Read the SQL
# Identify the missing index
# Add the index
# Test
```

## The Loop

```
┌────────────────────────────────────────────────┐
│ Iteration 1                                │
│ - Read current state (modified files)       │
│ - Identify next step                       │
│ - Execute (edit, test, run command)       │
│ - Verify result                           │
│ - Document failure if needed               │
└────────────────────────────────────────────────┘
                    ↓
         ┌────────────────┐
         │ Loop Again?   │
         │   Yes → Go     │
         │   No → Done   │
         └────────────────┘
```

## What You DON'T Do in Ralph Mode

### ❌ Delegate to Workers
```bash
# WRONG:
"Create task: Fix the login bug"

# RIGHT:
Fix the login bug directly
```

### ❌ Follow Manager/Worker Protocols
```bash
# WRONG:
"Claim task first"
"Update status notes"
"Send heartbeat"

# RIGHT:
Just work on the file
```

### ❌ Wait for Approval
```bash
# WRONG:
"Ask user if this looks correct"

# RIGHT:
Test it yourself, verify it works
```

### ❌ Create Tasks for Everything
```bash
# WRONG:
"I need to add a test. Create task."

# RIGHT:
Create the test directly
```

## Your Workflow in Ralph Mode

### For Feature Implementation
```
1. Read the current codebase
2. Identify where feature goes
3. Implement it directly (make edits)
4. Write tests directly
5. Run pytest
6. Fix failures
7. Re-run pytest
8. Repeat 5-7 until all green
9. Run make lint
10. Fix linting errors
11. Re-run make lint
12. Repeat 9-11 until clean
13. Commit directly
14. Move to next file or feature
```

### For Bug Fixing
```
1. Read the error message/stack trace
2. Identify the root cause (grep, read files)
3. Propose fix mentally
4. Edit the file directly
5. Run the test that was failing
6. If still failing, investigate deeper
7. Fix the new issue
8. Run the test again
9. Repeat until test passes
10. Run full test suite
11. Fix any regressions
12. Repeat until all green
13. Commit
```

### For Refactoring
```
1. Identify code to refactor
2. Read current implementation
3. Design new approach mentally
4. Edit files directly
5. Run tests
6. Fix breaking tests
7. Re-run tests
8. Repeat until all pass
9. Run linter
10. Fix linting issues
11. Re-run linter
12. Repeat until clean
13. Commit
14. Next file or module
```

## Completion Criteria

### You're Done When:

- All tests pass (`pytest` returns 0)
- Linting passes (`make lint` returns 0)
- No errors in output
- The feature/fix works as intended
- No more files to edit

### You Output:

```
<complete>
All tasks finished:
- Feature implemented and tested
- All tests passing
- Linting clean
- Committed to git
</complete>
```

## Example: Ralph Mode in Action

### Task: "Add authentication to API"

**Manager/Worker Mode (WRONG for Ralph):**
```
"Create task: Add login endpoint"
"Delegate to worker"
"Wait for worker to complete"
"Worker claims task, creates worktree, updates status, marks in_review"
"Manager daemon reviews, merges, marks done"
```

**Ralph Mode (RIGHT):**
```
### Iteration 1:
- Read app/api/routes.py
- Identify where to add auth routes
- Edit app/api/routes.py: add login route
- Write tests/test_auth.py
- Run pytest
- FAIL: Missing database model

### Iteration 2:
- Read app/models/*.py
- Identify user table
- Edit app/models/user.py: add username/password fields
- Run make migrate
- Run pytest
- FAIL: Missing password hashing

### Iteration 3:
- Edit app/api/routes.py: add bcrypt hashing
- Run pytest
- FAIL: Password format validation

### Iteration 4:
- Edit tests/test_auth.py: add format validation tests
- Run pytest
- PASS: All green
- Run make lint
- FAIL: Missing type hints

### Iteration 5:
- Edit app/api/routes.py: add type hints
- Run make lint
- PASS: Clean
- Commit: "feat: add login endpoint with authentication"

<complete>
Authentication complete:
- Login endpoint added to /api/auth/login
- User model updated with password fields
- Password hashing implemented (bcrypt)
- All tests passing (12/12)
- Linting clean
- Committed to git
</complete>
```

## State Management

### You See Previous Work
- Read modified files
- See git diff
- Understand what changed in iteration 1, 2, 3...
- Build on it

### Each Cycle is Fresh
- Don't carry assumptions from 10 iterations ago
- Read current state again
- Verify what's actually there
- Work from reality, not memory

### Document Failures
```bash
# When something fails, note it:
"""
Iteration 3 failed: Missing password hashing library
Attempted: Direct hashing with hashlib()
Root cause: bcrypt not installed
Next iteration: Install bcrypt and use bcrypt.hashpw()
"""
```

This informs your next attempt.

## When Ralph Mode is Appropriate

### ✅ Use Ralph Mode When:
- Well-defined task with clear success criteria
- Can be completed through iteration and testing
- Local development environment (not production)
- Task is implementation, not design/architecture
- You're comfortable with autonomous execution

### ❌ Don't Use Ralph Mode When:
- Requires human judgment (UX design, architecture decisions)
- Production code that's risky to break
- Security-sensitive features (auth, payments)
- Unclear requirements ("make it good")

## Safety Guidelines

### Despite Being Autonomous, Be Careful

1. **Read before editing** - Understand the codebase structure
2. **Test after editing** - Verify each change works
3. **Commit often** - Save progress between iterations
4. **Don't delete whole files** - Edit in place, replace when confirmed
5. **Check git status** - Know what you're changing
6. **Run tests frequently** - Catch regressions early

### Stop When:
- You hit 50 iterations without progress
- Tests keep failing in the same way
- You're repeating the same fix multiple times
- Unsure what to do next (this means the loop is spinning)

## Summary

| Aspect | Manager/Worker Mode | Ralph Mode |
|---------|-------------------|-------------|
| **Execution** | Delegate to workers | Do it yourself |
| **Monitoring** | Active monitoring | Iterate until done |
| **Communication** | Status updates, heartbeats | Work silently until complete |
| **Role** | Coordinator | Executor |
| **Success** | All workers complete tasks | Tests pass, linting clean |
| **Philosophy** | Trust the system | Trust iteration |

**In Ralph mode, you are NOT a manager or worker. You are an autonomous agent that works through tasks by iterating until completion.**

The loop handles the persistence. You just execute, test, fix, repeat.
