# Release Writer Agent

## Purpose

The Release Writer Agent is a read‑only reference that defines the minimum permissions and accepted output for the automated release‑writer workflow. It is used by the ChatGPT worker that sends the payload to the release service API.

## Permissions
- `contents:read`
- `metadata:read`
- `pull_requests:read`
- `checks:read`
- `workflows:read`
- **No write access** to source files, branches, or merge actions.

## Expected Payload
```json
{
  "sha": "<merge SHA>",
  "pr_title": "<merged PR title>",
  "pr_body": "<merged PR body>",
  "issues": ["<issue number>"],
  "changed_files": ["src/..."],
  "author": "<github username>",
  "created_at": "<ISO datetime>",
  "type": "feature|bug|docs|refactor|chore",
  "summary": "<short 1‑sentence summary>",
  "details": "<optional longer description>"
}
```

The agent *must not* output or handle any secrets.
