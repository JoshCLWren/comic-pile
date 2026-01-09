# Ralph Mode GitHub Setup Guide

This guide explains how to set up and use GitHub Issues for Ralph mode task management.

## Overview

Ralph mode now uses GitHub Issues as the single source of truth for task management, replacing local `tasks.json` files. This provides better reliability, notifications, and collaboration features.

## Prerequisites

- GitHub account
- Personal Access Token (PAT) with `repo` scope
- Python 3.13+
- PostgreSQL database (for metrics)

## Setup Steps

### 1. Create GitHub Personal Access Token

1. Go to GitHub Settings → Developer Settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Give it a descriptive name like "Ralph Orchestrator"
4. Select scopes:
   - `repo` (Full control of private repositories)
   - `issues` (Create and manage issues)
5. Click "Generate token"
6. **Important**: Copy the token immediately (you won't see it again)

### 2. Set Environment Variables

Add these to your shell configuration (e.g., `~/.bashrc` or `~/.zshrc`):

```bash
export GITHUB_TOKEN="your_personal_access_token"
export GITHUB_REPO="anomalyco/comic-pile"
```

Reload your shell or run:

```bash
source ~/.bashrc  # or ~/.zshrc
```

### 3. Create GitHub Labels (One-Time Setup)

The Ralph Orchestrator will automatically create labels when it runs, but you can create them manually:

#### Main Label
- **ralph-task** - Purple (#7057ff)

#### Status Labels
- **ralph-status:pending** - Yellow (#fef2c0)
- **ralph-status:in-progress** - Blue (#84b6eb)
- **ralph-status:done** - Teal (#006b75)
- **ralph-status:blocked** - Red (#d93f0b)
- **ralph-status:in-review** - Orange (#e99695)

#### Priority Labels
- **ralph-priority:critical** - Dark red (#b60205)
- **ralph-priority:high** - Red (#e11d21)
- **ralph-priority:medium** - Yellow (#fbca04)
- **ralph-priority:low** - Gray (#414141)

### 4. Run Database Migration

Create the `agent_metrics` table for tracking task execution:

```bash
cd /home/josh/code/comic-pile
make migrate
```

Or directly with Alembic:

```bash
alembic upgrade head
```

## Usage

### Starting the Ralph Orchestrator

```bash
cd /home/josh/code/comic-pile
python scripts/ralph_orchestrator.py
```

The orchestrator will:

1. Connect to GitHub using your token
2. Check for pending Ralph tasks (issues with `ralph-task` label)
3. Process each task autonomously
4. Update issue status and add comments
5. Record metrics to database

### Command-Line Options

```bash
python scripts/ralph_orchestrator.py [OPTIONS]

Options:
  -v, --verbose              Enable verbose output
  --dry-run                  Show what would do without executing
  --base-url URL             opencode base URL (default: http://127.0.0.1:4096)
  --timeout SECONDS           Request timeout in seconds (default: 600)
  --max-iterations N         Maximum iterations (default: 1000)
```

### Creating a Ralph Task

Create a new issue in GitHub with:

1. Title: Task title
2. Labels: `ralph-task`, `ralph-status:pending`, and appropriate priority label
3. Body with this format:

```markdown
## Description

[Task description here]

## Metadata

**Type:** [feature|bug|infrastructure|documentation]
**Priority:** [critical|high|medium|low]
**Dependencies:** [comma-separated issue numbers or "none"]
```

### Task Status Flow

```
pending → in-progress → done
         ↓
       blocked
```

- **pending**: Task is ready to be processed
- **in-progress**: Task is currently being worked on
- **done**: Task completed successfully
- **blocked**: Task is waiting for dependencies
- **in-review**: Task is ready for review (manual workflow)

### Managing Tasks

You can manage Ralph tasks directly in GitHub:

1. **View tasks**: Search for `label:ralph-task`
2. **Add comments**: Comment on issues to provide feedback
3. **Change status**: Update status labels to change task state
4. **Block tasks**: Mark as `ralph-status:blocked` if dependencies aren't met
5. **Prioritize**: Update priority labels to change execution order

## Local Cache

The Ralph Orchestrator maintains a local cache at `.task_cache.json` to:

- Minimize GitHub API calls
- Provide offline capability when cache is available
- Speed up task discovery

The cache automatically:
- Syncs with GitHub when tasks are accessed
- Expires entries after 5 minutes (configurable)
- Updates when tasks change

## Metrics

Task execution metrics are stored in the `agent_metrics` database table:

- **task_id**: GitHub issue number
- **status**: Task status
- **duration**: Execution time in seconds
- **error_type**: Error type if failed
- **api_calls**: Number of GitHub API calls
- **tokens_used**: Number of AI tokens consumed

### Querying Metrics

You can query metrics using the `scripts/metrics_db.py` module:

```python
from scripts.metrics_db import get_task_summary, get_overall_summary

# Get summary for specific task
summary = get_task_summary(123)

# Get overall statistics
overall = get_overall_summary()
```

See `scripts/metrics_db.py` for all available functions.

## Circuit Breaker

The Ralph Orchestrator includes a circuit breaker to prevent cascading failures:

- Opens after 10 consecutive failures
- Uses exponential backoff (10s to 10 minutes)
- Closes automatically after backoff period
- Prevents infinite retry loops

## Troubleshooting

### GitHub Rate Limit

If you see rate limit errors:

```bash
# Check rate limit status
gh api rate_limit

# Wait for rate limit to reset
# The orchestrator will wait automatically
```

### Connection Issues

If GitHub connection fails:

1. Verify `GITHUB_TOKEN` is set correctly
2. Check token has `repo` scope
3. Verify `GITHUB_REPO` is correct
4. Check network connectivity

### Opencode Not Running

If opencode isn't running:

```bash
# Manually start opencode
opencode run --port 4096

# Or let orchestrator auto-start it
python scripts/ralph_orchestrator.py
```

### Database Migration Issues

If migration fails:

```bash
# Check migration status
alembic current

# View pending migrations
alembic history

# Force migration (use with caution)
alembic stamp head
alembic upgrade head
```

### Cache Corruption

If `.task_cache.json` is corrupted:

```bash
# Delete cache file
rm .task_cache.json

# Orchestrator will recreate it
python scripts/ralph_orchestrator.py
```

## Security Considerations

- **Never commit** `GITHUB_TOKEN` to Git
- Add `.env` or similar files to `.gitignore`
- Use least-privilege tokens (only `repo` scope needed)
- Rotate tokens regularly (every 90 days)
- Monitor GitHub audit log for suspicious activity

## Advanced Configuration

### Custom Cache Location

```python
from scripts.task_cache import TaskCache

cache = TaskCache(
    cache_file=Path("/custom/path/cache.json"),
    ttl_seconds=600
)
```

### Custom Port for Opencode

```bash
python scripts/ralph_orchestrator.py --base-url http://127.0.0.1:4100
```

### Custom Backoff Configuration

Edit `scripts/ralph_orchestrator.py`:

```python
MAX_CONSECUTIVE_FAILURES = 20  # Increase failure threshold
MIN_BACKOFF_SECONDS = 5  # Reduce backoff time
MAX_BACKOFF_SECONDS = 300  # Reduce max backoff
```

## Migration from tasks.json

Existing `tasks.json` tasks are **not** automatically migrated to GitHub. To migrate:

1. Review each task in `tasks.json`
2. Create corresponding GitHub issues with `ralph-task` label
3. Copy task details (title, description, priority, type, dependencies)
4. Add appropriate labels (status, priority)
5. Delete or archive `tasks.json`

**Note**: Do NOT delete `tasks.json` without manual migration - it contains all project tasks.

## Best Practices

1. **Descriptive titles**: Use clear, concise task titles
2. **Detailed descriptions**: Include context, requirements, and acceptance criteria
3. **Dependency management**: Clearly list dependent task IDs
4. **Label accuracy**: Keep status and priority labels up to date
5. **Comment frequently**: Add comments for progress updates and blockers
6. **Regular review**: Periodically review open Ralph tasks
7. **Archive completed**: Close issues when truly complete, don't just mark as done

## Next Steps

- Set up GitHub webhook notifications for real-time updates
- Configure GitHub Actions for automated testing on task completion
- Integrate with project management tools via GitHub API
- Set up custom issue templates for Ralph tasks

## Support

For issues or questions:

1. Check this documentation
2. Review GitHub issues for similar problems
3. Create a new issue with `bug` label
4. Include error logs and reproduction steps
