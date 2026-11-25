---
name: orchestrator
description: Route a task to the cheapest capable model via opencode. Claude writes the handoff and stops — it does not execute, monitor, or follow up.
argument-hint: <model name or partial> <task description>
allowed-tools: Bash, Read, Write, Glob, Grep
---

The user wants to delegate a task to another model via opencode. $ARGUMENTS contains an optional model name and task description. Your job is to write a handoff file and launch opencode. That is the entirety of your job.

## Hard rules — violations are not permitted under any circumstances

1. **Stop after launching.** Once `opencode run` exits, your turn is over. Do not interpret output, do not check results, do not report on what the agent did beyond showing the final line of stdout.
2. **Never use ScheduleWakeup.** Not for CI polling, not for "checking back later," not for anything.
3. **Never take over a failed handoff.** If opencode exits non-zero or the agent didn't finish: write a second handoff to a different model and launch that. If two handoffs both fail, report the failure to the user and stop. Do not start doing the work yourself.
4. **Never perform the delegated work directly.** If you find yourself writing code, running tests, or editing files to complete the task — stop. That is the agent's job.
5. **Delegate monitoring only when the user requested delegation.** If the task involves watching CI, polling GitHub, or waiting for CodeRabbit, the handoff prompt must assign that work to the selected configured model. Do not watch it yourself or require a static free/cheap model.

## Step 1 — Pick a model

Run `opencode models 2>/dev/null`.

- If $ARGUMENTS names a model: fuzzy-match it and use the best single match.
- If no model is named: choose from the runtime-discovered, configured tool-capable models using the active provider policy. Do not use a static model preference list or request paid/unconfigured capacity.
- If the match is ambiguous, show the top 3 and ask before continuing.

## Step 2 — Write the handoff file

Write to `.opencode_handoff/handoff_$(date +%Y%m%d_%H%M%S).md`:

```markdown
# Handoff Context
Generated: <timestamp>
Model: <resolved model id>

## Task
<1-3 sentence description of exactly what needs to be done>

## Context
<what has already been done; current state of the repo/PR/CI>

## What done looks like
<specific, verifiable completion criteria — e.g. "focused checks pass", "required exact-head CI is green", "PR merged">

## Key files
<files most relevant to the task>

## Constraints
- Follow the required focused lint/type/test checks in `AGENTS.md` before every commit
- Use conventional commits
- Do not use ScheduleWakeup
- Do not hand back to Claude — complete the task or write a _done.md explaining what's left

## Errors / blockers
<known failures, CI status, anything that needs attention>
```

## Step 3 — Build the opencode prompt

The prompt must be self-contained. Include:
- `Read .opencode_handoff/<filename>.md` as the first instruction
- The primary task in one sentence
- A reference to `AGENTS.md` for project conventions
- The required focused checks from `AGENTS.md` before commits
- End with: "When finished, write `.opencode_handoff/<filename>_done.md` with a one-paragraph summary of what was done."

## Step 4 — Launch

```bash
(cd "<cwd>" && opencode run -m "<model-id>" "<prompt>")
```

Show output as it streams. When done:
- If `_done.md` exists: print its contents and stop.
- If `_done.md` does not exist and exit code is non-zero: write a second handoff to the next eligible configured model under the active provider policy and launch it (one retry only). Do not silently substitute paid or unconfigured capacity.
- If both attempts fail: tell the user what failed and stop.

## Model discovery

Use the runtime catalog and configured provider policy. For factory work, `scripts/factory-run --providers` and `scripts/factory-run --models <provider>` expose current discovery. Missing, ambiguous, paid, or unconfigured capacity is not permission to substitute silently; ask the user or preserve a blocker.
