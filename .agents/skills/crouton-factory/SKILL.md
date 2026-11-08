---
name: crouton-factory
description: Orchestrate Comic Pile factory work as a lean foreground coordinator — Jev advisory choices, atomic local-factory label claims, ACP/Codex parallel review lanes, exact-head CI gating, browser-only QA, and cleanup. Use when driving an end-to-end issue slice from claim through merge, when coordinating multiple workers, or when you must keep the main context lean while subagents do the file work.
metadata:
  opencode/slash: "true"
---

# Crouton factory — lean orchestrator loop

Foreground (main agent) = orchestrator only: **Jev calls, label writes, verdict reads, lane starts/stops**.
All file reads, edits, builds, test runs, logs, and diffs live in subagents / Codex. Never dump a 900-line file, full transcript, or raw CI log into foreground context.

Distilled from this session's live traffic: `ses_ec59129b1ffekTr6nNL7bVmG5K` + `ses_ecf4efa10ffeMliKulhJceQhFX` era, PRs **#4804** (G4 SQL budget `local/4347-g4-budget`), **#4805** (G6 probe `local/4347-g6-probe`), **#4794** (retire shadow python #4347), **#4792** (REPLACE set-die #4352), **#4797** (MIGRATE continuity-plan #4346), **#4802** (retire oracle #4738), plus `/tmp/opencode/jev-skill-recovered.md` and `/tmp/opencode/labels-4347*.json` artifacts.

## Workflow diagram

```text
Jev consult (advisory, decisive flag)
  └─> claim (atomic PUT, one owner)
        └─> ACP/Codex fan-out envelope (parallel lanes)
              └─> verdict consolidation (FACTORY_GATE_READY / BLOCKED)
                    └─> merge (exact-head gates only)
                          └─> release (factory:review + factory:unowned)
                                └─> QA (browser-only, read-only)
                                      └─> cleanup (eligible-only sweep)
                                            └─> next Jev slice (loop, never poll CI)
```

Foreground never writes code. It starts one lane, then Jev-picks the next slice while the lane runs.

## (a) Jev consult-before-decision loop

Advisory only. User instructions, security, ownership, and verification gates override Jev. (`/tmp/opencode/jev-skill-recovered.md`, `docs/AUTONOMOUS_FACTORY_POLICY.md` Jev selection.)

```js
await tools.jev.consult({
  question: "<next meaningful decision>",
  context: "<sanitized summary — no secrets, no raw private docs>",
  criteria: "<what good looks like: small, reviewable, preserves behavior>",
  options: [
    { id: "a", description: "<eligible option A>" },
    { id: "b", description: "<eligible option B>" },
  ],
})
```

Rules:

- 2–8 options, each `{id, description}`, all already eligible. Never ask the user to pick among Jev options.
- Report `choice` **and** the decisive/confidence flag. If `decisive: false`, say so — do not pretend Jev decided.
- If Jev is silent or the choice is non-decisive and risky, take the smallest additive slice.
- Never poll: `gh pr checks <pr> --watch --interval 30` runs in **background shell**. A later push invalidates that watch; restart it for the new head.

## (b) Local-factory claim/release label machine

One owner at a time. Atomic full-set `PUT`, never sequential add/remove (POST only accumulates stale owners). (`/tmp/opencode/labels-4347.json` → `labels-4347-review.json`.)

```sh
# CLAIM (before first edit) — issue
gh api -X PUT repos/JoshCLWren/comic-pile/issues/<N>/labels \
  -F "labels[]=factory" -F "labels[]=factory:building" -F "labels[]=factory:local" \
  -F "labels[]=ralph-status:in-progress" \
  -F "labels[]=<preserve every unrelated label from live read>"

# CLAIM — PR
gh api -X PUT repos/JoshCLWren/comic-pile/issues/<PR>/labels \
  -F "labels[]=factory" -F "labels[]=factory:building" -F "labels[]=factory:local"

# RELEASE (immediately after push, fleet only claims factory:unowned) — issue
gh api -X PUT repos/JoshCLWren/comic-pile/issues/<N>/labels \
  -F "labels[]=factory" -F "labels[]=factory:review" -F "labels[]=factory:unowned" \
  -F "labels[]=ralph-status:in-review" -F "labels[]=<preserve unrelated>"

# RELEASE — PR: factory + factory:review + factory:unowned
```

- Never fight scheduled factories `factory:1`–`factory:96`. If live labels show another active owner, skip/stop; do not steal back. (`local-factory-next-task` §3, `make next-task` ordering.)
- Lease alive rule: `factory:local` expires after 60 min without GitHub-recorded activity. Post a truthful progress comment every ~45 min; local commits alone don't count.
- `factory:review`/`factory:ci`/`factory:ready` with `factory:unowned` still means "do not start implementation" — advance that PR instead.

## (c) Exact-head CI gating + 24h stale-bot beat

- Gates apply to the **exact head SHA**. Any push invalidates prior CI; re-read head SHA before reporting any result.
- Never end ordinary work with "CI pending". Either keep working the next Jev slice or state the exact head still under exact-head CI.
- A skipped coverage job from an upstream failure is not a pass. Green early bootstrap ≠ full CI success.
- `comic-pile-factory-stale-expiration-v1` closes factory PRs idle ~24h (`threshold-86400`) and releases the issue to `factory:unowned`. On stale-close: open a fresh PR from the same branch (GitHub refuses reopen after force-push), rebase onto current `main`, re-run every gate, re-apply pickup labels, and point the issue at the new PR. (`local-factory-session` §Stale-expiration.)

## (d) Independent review — ACP + Codex parallel lanes

Never single-model self-approval. Fan out **two independent reviewer lanes minimum** at exact head, verdict-only returns. Evidence: `/tmp/opencode/review-4627-prompt-a.txt` + `-b.txt` (dual-lane envelope for PR #4627), `/tmp/opencode/pr4797-review/`, `/tmp/opencode/review4685/`, `.factory-gate-status.txt` (`FACTORY_GATE_READY`).

Reviewer envelope (copy-paste):

```text
You are an independent <semantic|skeptical> reviewer for Comic Pile PR #<N> at exact head <sha>.
Do not edit any file, do not commit, do not push, do not change GitHub metadata.
Read the PR diff against origin/main, the changed files, issue #<N>, AGENTS.md,
docs/OBJECTIVE_FIRST_ENGINEERING_CONTRACT.md, docs/AUTONOMOUS_FACTORY_POLICY.md, and prior review threads.
Answer: (1) Correctness/safety. (2) Objective/acceptance — does the PR overstate completion?
Report concise findings with file:line evidence.
If no blocking correctness/security/ownership/data-integrity/migration/concurrency/recovery/false-completion issue remains, end with exactly:
FACTORY_GATE_READY
Otherwise end with exactly:
FACTORY_GATE_BLOCKED
The final line must be the marker itself and nothing else.
```

Foreground consolidates verdicts only — no file dumps. Either lane `BLOCKED` ⇒ orchestrator Jev-picks the repair slice, re-claims, and re-fans-out. Two `READY` + green exact-head CI ⇒ merge-eligible.

## (e) Playwright QA is browser-only (read-only)

QA agents: **measure, don't edit**. No spec edits by QA agents — spec fixes are factory implementation slices. (`e2e-chromium-regression` skill, `docs/E2E_CHROMIUM_REGRESSION.md`.)

- QA lane inputs: `frontend/test-results/regression/results.json`, slot-unique backend log, traces (`trace.zip` → `.network` JSONL), HTML report, screenshots/videos.
- QA lane outputs: inventory-ordered finding list (P0 vs P1/P2) with repro steps and artifact pointers. One canonical issue per P1/P2 root cause; never skip/delete a spec to get green.
- Full browser contract (port slot, postgres-only, frontend build, backend env) lives in `e2e-chromium-regression`; QA lane must honor it verbatim — see (h).

## (f) Context diet

| Foreground (main) | Delegated (subagent / Codex) |
|---|---|
| Jev calls, label `PUT`s, verdict markers | All file reads, edits, builds, test/log tailing |
| Lane start/stop, merge-eligibility calls | Diffs, stack traces, PR bodies, large JSON |
| One-line status per lane | Anything > ~50 lines of file/log output |

- One session = one private worktree (`/mnt/extra/josh/code/comic-pile-<issue>`). Never share a checkout across agents. (Evidence: `/tmp/opencode/4347-g4`, `/tmp/opencode/4347-g6`, `/tmp/opencode/4738-retire`, `/tmp/opencode/roll004-fix2`.)
- Claim a port slot N in 1–9 for the whole session (`PORT=8000+N`, `BASE_URL=9000+N`, `E2E_POSTGRES_PUBLISH=5437+N`). (`local-factory-next-task` §1.)
- Subagent prompt = smallest possible envelope: exact head, file list, acceptance question, verdict marker. Foreground reads only the verdict + 3-line summary.

## (g) Cleanup agent

Dedicated lane; foreground only reads the eligible-only tally. Never `rm -rf` a worktree by hand from foreground.

- Locked worktrees preserved. Evict only: merged-PR worktrees, or clean unmerged worktrees with no active owner and no in-flight branch.
- Rust: `/home/josh/.local/bin/rust-build-cache` (dry-run default). Apply with `--run comic-pile -- <cmd>` and `--apply` for eligible-only accounting; never hand-delete `/mnt/bigdata` targets, never set `CARGO_TARGET_DIR`. (AGENTS.md Rust budget rule.)
- Sweep: `/tmp/opencode` orphaned lane dirs (stale `4347-g*` clones), browser-orphan processes under the session's port slot, stale `tool-output`. Report `eligible` vs `skipped(approved)`; foreground approves only.

## (h) Frontend + browser lane contract

- **Before any frontend edit, read `docs/FRONTEND_VISUAL_GRAMMAR.md`** (canonical; `frontend/AGENTS.md` is supplemental). Identify the grammar rule being followed; do not invent a new dialect because nearby code drifts. New surfaces use semantic `--theme-*` roles; raw Tailwind hex is local-effect-only.
- **P0 = owned, must stay green** (blocks the change). **P1/P2 = discovery** (catalogue, group by root cause, file one canonical issue, then normal product work). (`e2e-chromium-regression` scope rules.)
- **Browser runs: `TEST_ENVIRONMENT=true` mandatory** (else the `app/middleware/rate_limit.py` gate 429-storms fixture traffic). Never pass `REDIS_URL`. Backend log path must be slot-unique (`/tmp/backend-<port>.log`), never machine-global `/tmp/backend.log`. uvicorn has no `--reload` — restart after backend edits.

## ACP/Codex fan-out envelope (canonical)

```text
Lane: <ACP subagent | codex exec>   Head: <sha>   Issue: #<N>   PR: #<M>
Scope: <changed files only>         Question: <single acceptance question>
Mode: <implement | review | QA-measure | cleanup-sweep>
Budget: <targeted tests + lint/typecheck only; full suites run in CI>
Return: <FACTOR_GATE_READY | FACTORY_GATE_BLOCKED | QA findings | eligible tally> + ≤3-line summary. No code dumps.
```

Run implementation lanes serially per issue; run review lanes for the same head in parallel. QA runs only after exact-head CI is green.

## Checklist template (copy-paste per slice)

```markdown
- [ ] Jev consult recorded (choice, decisive flag, options)
- [ ] Live labels re-read; claim PUT atomic (factory:building + factory:local, one owner)
- [ ] Private worktree + port slot N claimed; hooks verified (core.hooksPath, OPENCODE_MODEL)
- [ ] Implementation slice done (small additive diff, regression test included)
- [ ] Targeted gates passed (python: scripts/check-python-ci-lint.sh; frontend: lint/typecheck/build; browser: focused Playwright)
- [ ] Commit trailer present (Model: <id> / Authoring session: …); pushed, PR ready-for-review
- [ ] Release PUT atomic (factory:review + factory:unowned); progress comment posted
- [ ] exact-head CI green (gh pr checks --watch, head SHA re-read); 24h stale check clear
- [ ] Dual independent reviews returned (ACP + Codex, both verdict markers)
- [ ] Merge gate checked; QA browser-only pass filed; cleanup eligible-only sweep recorded
```

## When to stop / start a lane

| Signal | Action |
|---|---|
| `FACTORY_GATE_BLOCKED` from either reviewer | Stop merge lane. Jev-pick repair slice, re-claim, re-fan-out. |
| CI red on exact head | Stop. Targeted local repro → fix → new head → restart exact-head watch. |
| PR idle ≥ 24h, stale-bot closes it | Stop. Fresh PR from same branch + rebase + full gates + pickup labels. |
| Live labels show `factory:<n>` or fresh `factory:local` owner | Stop. Do not overwrite; pick next uncontended candidate (`make next-task`). |
| `decisive: false` + risky choice | Take smallest additive slice; never ask the user to pick. |
| QA finds P0 red | QA stops at report. Factory slice fixes specs/product before push. |
| QA finds P1/P2 reds only | QA stops at catalogued findings. File one canonical issue; do not block merge. |
| Two `READY` + green exact-head CI + no open Greptile blockers | Start merge, then release + QA + cleanup lanes. |
| Slice complete, pushed, released | Immediately Jev-pick next slice; never end a turn on "CI pending". |

## Never

- Never do file work in foreground, never dump 900-line files/transcripts into main context.
- Never self-approve: no merge on a single model's verdict.
- Never POST labels (accumulates stale owners); always atomic PUT of the complete set.
- Never leave an open factory PR without `factory` + one workflow-state + one owner label.
- Never edit `docs/changelog.md` / `docs/changelog.d/` for implementation PRs; never enable auto-merge.
- Never skip tests, never use CI as a debugger, never suppress lint/type findings.
- Never let a QA agent edit specs or product code; never let a cleanup agent touch locked/in-flight worktrees.
- Never start a browser run without `TEST_ENVIRONMENT=true` and a slot-unique backend log.
