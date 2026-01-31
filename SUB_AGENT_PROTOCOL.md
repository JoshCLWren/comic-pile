# Sub-Agent Coordination Protocol

## Quality Standards
- **ALL fixes must pass**: `ruff check`, `ty check --error-on-warning`, and relevant tests
- **Code review is mandatory**: 2nd sub-agent must verify fix before marking DONE
- **Be critical**: If you see ANY issue (new bugs, style violations, incomplete fixes), REJECT
- **No lazy fixes**: Must address root cause, not just suppress warnings

## Assignment Format
When assigning a fix to a sub-agent, include:
- Issue ID and description
- File and line number
- Expected behavior
- Verification commands
- "CRITICAL: If you create new problems, you will be reprimanded"

## Review Format
Peer reviewer must check:
1. Does the fix actually solve the problem?
2. Did it introduce new issues? (run linters/tests)
3. Is the code clean and follows project conventions?
4. Are there edge cases not handled?

## State Transitions
```
TODO → IN_PROGRESS (assign to sub-agent)
IN_PROGRESS → REVIEW (sub-agent claims fix is done)
REVIEW → DONE (peer reviewer approves + linters/tests pass)
REVIEW → FAILED (peer reviewer rejects, update with reason)
FAILED → IN_PROGRESS (retry with feedback)
```

## Current Assignments
| Issue ID | Sub-Agent | Reviewer | Status |
|----------|-----------|----------|--------|
| None | None | None | Ready to start |
