---
name: jev-nonblocking-loop
description: Run Jev-driven, non-blocking work loops without sitting on CI. Use when the user asks for Jev suggestions, says "keep going", "don't ask me, ask Jev", or wants coroutine-style continuation. Triggers on Jev consult decisions, background CI watches, and factory claim/release cycles.
metadata:
  opencode/slash: "true"
---

# Jev non-blocking loop

Drive work via Jev advisory choices and keep moving while slow gates run in the background. Never poll, sleep, or sit on CI.

## Jev consultation loop

1. Before choosing a direction, call `tools.jev.consult` (via `execute`) with:
   - `question`: the next meaningful decision
   - `context`: sanitized summary (no secrets, no private raw docs)
   - `criteria`: what "good" means (small, reviewable, preserves behavior)
   - `options`: 2-8 already-eligible options, each with `id` + `description`
2. Follow the returned `choice` unless it conflicts with user instructions, security, ownership, or verification gates. Advisory only.
3. If `decisive` is false or confidence is low, say so in the report — do not pretend Jev decided.
4. Never ask the user to choose among Jev options. If Jev is silent or the choice is non-decisive and risky, take the smallest additive slice.

## Coroutine style — never block

- Start slow waits in the **background**: `gh pr checks <pr> --watch --interval 30` with background shell. You get notified on completion; do not poll or `sleep`.
- While background work runs, immediately do the next Jev-picked slice (code, test, doc) in the foreground.
- A later push invalidates prior CI. Restart the exact-head watch for the new head after each push. Do not report "CI pending" as done.

## Factory claims — claim, then release

Every slice must claim and release:

1. **Claim** before editing (atomic label replacement, never sequential add/remove):
   - Issue: `["factory","factory:building","factory:local","ralph-status:in-progress"]`
   - PR: `["factory","factory:building","factory:local"]`
   ```sh
   gh api --method PUT repos/JoshCLWren/comic-pile/issues/<N>/labels --input labels.json
   ```
2. **Release** immediately after push to review pickup (fleet only claims `factory:unowned`):
   - Issue: `["factory","factory:review","factory:unowned","ralph-status:in-review"]`
   - PR: `["factory","factory:review","factory:unowned"]`
3. One owner label at a time. Re-claim before the next slice.

## Commits & pushes

- One atomic imperative commit per Jev slice. Verify first (targeted tests + frontend lint/typecheck or `bash scripts/check-python-ci-lint.sh`).
- Trailer (hooks may be inert on Cursor — write by hand):
  ```
  Model: <exact model id>
  Authoring session: interactive <host> session, no registered factory-worker identity
  ```
- Push to the PR branch immediately. Do not leave completed work local.

## Reports

- Each report: Jev choice + confidence/decisive flag, what was claimed/released/pushed, verification run, and background shell ID still running.
- Never end ordinary work with only "CI pending". Either keep working the next Jev slice or state the exact head still under exact-head CI.
