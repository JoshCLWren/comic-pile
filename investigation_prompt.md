# Investigation Task: Issue #504 - 500 Error on Issue Creation

## Problem Statement
User is experiencing 500 errors when creating issues via the API endpoint:
```
POST /api/v1/threads/{thread_id}/issues
```

## Reproduction Case
```bash
curl 'https://app-production-72b9.up.railway.app/api/v1/threads/377/issues' \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token>' \
  --data-raw '{"issue_range":"esadfas3","insert_after_issue_id":10882}'
```

## What We Know
1. The endpoint is in `app/api/issue.py` function `create_issues`
2. Issue #504 title says "updating the issue of a thread read causes 500s"
3. Recent changes enabled `autoflush=True` in database.py and removed manual flush calls
4. The issue is happening in PRODUCTION (Railway) but not obviously in local tests
5. The issue_range "esadfas3" parses as a single issue number "esadfas3" (valid)

## What We DON'T Know
1. What is the ACTUAL error message from production?
2. Is it related to MissingGreenlet, IntegrityError, or something else?
3. Why is it happening in production but not local tests?
4. Is it data-specific (thread 377, issue 10882)?

## Investigation Tasks
1. **Find the actual error**: Check if there are logs, error tracking, or stack traces from the Railway deployment
2. **Understand the data**: What's special about thread 377 and issue 10882?
3. **Check for race conditions**: Are there concurrent operations?
4. **Database state**: Is the database in production different from local?
5. **Review recent changes**: What changed besides autoflush?
6. **Check similar endpoints**: Do other issue-related endpoints have the same problem?

## Important Notes
- DO NOT assume it's related to autoflush changes (user says it happened before too)
- DO NOT make changes without understanding the root cause
- FOCUS on finding the actual error message first
- The user says "your fix didn't fix the actual issue causing 500s"

## Files to Investigate
- `app/api/issue.py` - create_issues endpoint
- `app/database.py` - database configuration
- `app/models/thread.py` - get_issues_remaining method
- Railway logs/monitoring
- Any error tracking (Sentry, etc.)

## Next Steps
1. Get actual production error logs
2. Reproduce locally with production-like data
3. Identify root cause
4. Propose fix
