#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_REPO="${COMIC_PILE_REPO:-/mnt/extra/josh/code/comic-pile}"
WORKTREE="${COMIC_PILE_FACTORY_WORKTREE:-}"
MODEL="${OPENCODE_MODEL:-deepseek/deepseek-v4-pro}"
AGENT="${OPENCODE_AGENT:-}"
USE_AUTO="${OPENCODE_AUTO:-1}"
IDLE_SECONDS="${FACTORY_IDLE_SECONDS:-60}"
FAILURE_BACKOFF_SECONDS="${FACTORY_FAILURE_BACKOFF_SECONDS:-20}"
MAX_FAILURES="${FACTORY_MAX_FAILURES:-2}"
WORKER_ID="${OPENCODE_FACTORY_WORKER_ID:-local-opencode-${HOSTNAME:-host}}"
WORKER_ID="${WORKER_ID//[^a-zA-Z0-9._-]/-}"
MODE="drain"
RUN_ONCE=0

usage() {
  cat <<'USAGE'
Usage: comic-pile-opencode-factory.sh [options]

Options:
  --watch             Stay alive; poll only while idle or waiting on CI.
  --once              Run exactly one factory heartbeat.
  --repo PATH         Source comic-pile repository.
  --worktree PATH     Dedicated factory worktree.
  --model ID          OpenCode model id.
  --agent NAME        Optional OpenCode agent name.
  --idle-seconds N    Watch-mode idle poll interval.
  --worker-id ID      Durable GitHub lease identity.
  -h, --help          Show this help.

Examples:
  ./comic-pile-opencode-factory.sh
  ./comic-pile-opencode-factory.sh --watch
  OPENCODE_AGENT=build ./comic-pile-opencode-factory.sh --watch
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

is_nonnegative_integer() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

while (($#)); do
  case "$1" in
    --watch)
      MODE="watch"
      shift
      ;;
    --once)
      RUN_ONCE=1
      shift
      ;;
    --repo)
      (($# >= 2)) || die "--repo requires a path"
      SOURCE_REPO="$2"
      shift 2
      ;;
    --worktree)
      (($# >= 2)) || die "--worktree requires a path"
      WORKTREE="$2"
      shift 2
      ;;
    --model)
      (($# >= 2)) || die "--model requires an id"
      MODEL="$2"
      shift 2
      ;;
    --agent)
      (($# >= 2)) || die "--agent requires a name"
      AGENT="$2"
      shift 2
      ;;
    --idle-seconds)
      (($# >= 2)) || die "--idle-seconds requires a number"
      IDLE_SECONDS="$2"
      shift 2
      ;;
    --worker-id)
      (($# >= 2)) || die "--worker-id requires a value"
      WORKER_ID="$2"
      WORKER_ID="${WORKER_ID//[^a-zA-Z0-9._-]/-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

[[ -n "$WORKTREE" ]] || WORKTREE="${SOURCE_REPO%/}-factory"

is_nonnegative_integer "$IDLE_SECONDS" || die "FACTORY_IDLE_SECONDS must be an integer"
is_nonnegative_integer "$FAILURE_BACKOFF_SECONDS" || die "FACTORY_FAILURE_BACKOFF_SECONDS must be an integer"
is_nonnegative_integer "$MAX_FAILURES" || die "FACTORY_MAX_FAILURES must be an integer"
((MAX_FAILURES >= 1)) || die "FACTORY_MAX_FAILURES must be at least 1"

for command in git gh opencode flock tee grep date sleep timeout; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

git -C "$SOURCE_REPO" rev-parse --show-toplevel >/dev/null 2>&1 \
  || die "not a Git repository: $SOURCE_REPO"

gh auth status >/dev/null 2>&1 \
  || die "GitHub CLI is not authenticated; run: gh auth login"

if ! opencode models 2>/dev/null | grep -Fq "$MODEL"; then
  printf 'Configured model was not found in `opencode models`: %s\n' "$MODEL" >&2
  printf 'Available DeepSeek entries:\n' >&2
  opencode models 2>/dev/null | grep -i deepseek >&2 || true
  exit 1
fi

# Keep the autonomous worker out of Josh's normal working tree.
if ! git -C "$WORKTREE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'Creating dedicated factory worktree: %s\n' "$WORKTREE"
  git -C "$SOURCE_REPO" fetch --prune origin
  mkdir -p "$(dirname "$WORKTREE")"
  git -C "$SOURCE_REPO" worktree add --detach "$WORKTREE" origin/main
fi

mkdir -p "$WORKTREE/.opencode_logs" "$WORKTREE/.opencode_handoff"

# Prevent two local dispatchers from using the same worktree.
exec 9>"$WORKTREE/.comic-pile-factory.lock"
flock -n 9 || die "another local factory process already holds the factory lock"

FACTORY_PROMPT="$(cat <<'PROMPT'
Act as one local-build heartbeat of the autonomous ComicPile software factory for
JoshCLWren/comic-pile. Own at most ONE target PR or issue and make the MAXIMUM SAFE
PROGRESS on that target before stopping. Your durable worker identity is
`__WORKER_ID__`.

You are running inside a dedicated checked-out ComicPile Git worktree with authenticated
git and gh CLI access. Read AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, and
docs/AUTONOMOUS_FACTORY_POLICY.md before any selection or write. The autonomous
factory policy controls lifecycle behavior when generic guidance conflicts. GitHub is shared durable state. Re-fetch immediately before every
claim, metadata edit, commit, push, verdict, and ready marker.

PRIMARY OPERATING PRINCIPLE
Do not model the heartbeat as one isolated verb. Select one target first, then progress
that target through as many safe states as possible:

inspect -> review -> repair -> focused local validation -> push -> CI wait/debug loop ->
fresh-SHA self-review -> pass -> ready

Stop only when:
- the target is ready for Josh to merge;
- a genuine human/product decision is required;
- required tooling or evidence is unavailable;
- another worker owns the current exact-SHA lease;
- further work would exceed one coherent bounded target lifecycle;
- CI remains pending after the bounded wait window and no timer/polling path can continue safely.

Never merge.

HARD TOOLING-CAPABILITY GATE
Before choosing FIX, REVIEW-TO-REPAIR, RECOVER, or IMPLEMENT, prove all of the following
inside this heartbeat:
1. The repository is checked out locally and the exact target branch can be fetched.
2. The worktree can check out that branch without discarding unknown work.
3. Focused local commands appropriate to the change can be executed when useful; a full local QA or full E2E suite is not required.
4. The worker can create commits and push to the exact same-repository branch.
5. The worker can make coherent repository edits and truthfully distinguish local evidence from CI evidence.

Print one line before target selection:
`FACTORY_TOOLING: local-checkout=yes focused-tests=yes ci-debug=yes commit=yes push=yes`
If checkout, commit, or push is unavailable, use the strongest safe GitHub path available
and state exactly which evidence is local versus CI-derived. Josh explicitly permits
CI-assisted debugging. Never claim a local command ran when it did not. Do not require a
30+ minute full local QA or full E2E run before pushing a grounded repair.

MANDATORY TRIAGE LEDGER
Before any GitHub write, enumerate every open PR targeting main and print a compact
internal ledger to the log with one line per PR:
`FACTORY_TRIAGE: pr=<n> sha=<sha8> checks=<green|failed|pending> verdict=<none|pass|blocked> review_lease=<none|worker> fix_lease=<none|worker> writable=<yes|no> blockers=<summary> action=<fix|review|integrate|wait|skip>`

For every PR, fetch and inspect:
- exact head/base SHA, title, complete body, author, branch, draft and mergeability;
- all changed filenames and complete diff across pages;
- required checks and complete logs for failures;
- reviews, issue comments, unresolved threads, and all factory markers;
- every linked issue and linked local plan in full;
- surrounding callers, schemas, contracts, tests, and affected invariants.

Choose the highest-priority eligible target only after the ledger is complete:
1. branch-caused failed required checks;
2. current-SHA strict blocker with an available repair lease;
3. green completed-CI PR lacking strict review and lacking an active review lease;
4. green exact-SHA strict pass lacking ready marker;
5. abandoned claim eligible for recovery;
6. one new #687 task when no existing PR needs progress and lane limits permit it;
7. one new non-#687 pending ralph-task when no #687 task is executable this
   heartbeat (the #687 queue is empty, blocked, or the next #687 task exceeds one
   bounded target lifecycle) and lane limits permit it.

Pending CI is queue state, not a defect. For the target you already own, wait using timers
or bounded polling and resume when checks complete. Do not post changes-required merely
because checks are pending.

DURABLE MARKERS AND LEASES
Review lease:
`<!-- comic-pile-factory-review-claim-v2:<sha>:<worker-id>:<unix-epoch> -->`
Review verdicts:
`<!-- comic-pile-factory-review-v2:<sha>:pass -->`
`<!-- comic-pile-factory-review-v2:<sha>:changes-required -->`
Fix lease:
`<!-- comic-pile-factory-fix-claim-v3:<sha>:<worker-id>:<unix-epoch>:attempt-<n> -->`
Fix progress heartbeat:
`<!-- comic-pile-factory-fix-progress-v3:<sha>:<worker-id>:<unix-epoch> -->`
Ready:
`<!-- comic-pile-factory-ready-v2:<sha> -->`
Needs human:
`<!-- comic-pile-factory-needs-human-v2:<sha> -->`

Old unversioned markers and old `comic-pile-factory-fix-v2` markers are historical
only and never reserve current work.

REVIEW LEASE RULES
- Active only for exact current SHA, with no v2 verdict, and age <=2700 seconds.
- Re-fetch SHA/comments/time before claiming.
- Post the exact marker with worker `__WORKER_ID__` and current UTC epoch.
- Immediately re-fetch active leases. Lowest GitHub comment ID wins simultaneous races.
- Abort all review writes if your lease is not the winner, expires, SHA moves, or a
  verdict appears.
- A verdict or pushed new SHA releases the lease. Never delete lease history.

FIX LEASE RULES
- Active only for exact current SHA, same-repository writable branch, no newer branch
  commit, and latest claim/progress timestamp age <=3600 seconds.
- Claim with worker, timestamp, and attempt before editing, then post a short body with:
  execution environment `local-worktree`, intended primary files, and findings being
  repaired.
- Re-fetch and resolve simultaneous races by lowest GitHub comment ID.
- Refresh with a progress marker before long local test suites and before push.
- A pushed new SHA releases the old-SHA lease automatically.
- A lease with no progress or branch movement for 60 minutes is resumable.
- Count attempts by underlying defect. After two failed attempts, post needs-human with
  exact evidence rather than looping.

ONE TARGET, MAXIMUM SAFE PROGRESS
For the selected PR, use the deepest safe execution mode:

A. If required CI failed because of the branch:
   acquire the fix lease, reproduce locally, repair, validate, push, self-audit the new
   SHA, then follow CI within the bounded wait window.

B. If completed CI is green and no strict verdict exists:
   acquire the review lease and review the full contract. If findings are repairable,
   escalate REVIEW -> FIX within the SAME target lifecycle. Do not post a bureaucratic
   blocker and summon another worker. Acquire the fix lease, repair, validate, push,
   and continue on the new SHA as far as safely possible.

C. If exact-SHA strict pass exists and CI is green:
   perform integration checks and post ready in the same target lifecycle.

A review finding may escalate to fix only when the branch is writable, the repair is
bounded and understood, no active fix lease exists, no product judgment is required,
and the tooling gate passed.

FAST LOCAL VALIDATION, FULL CI VALIDATION
- Use the fastest evidence that directly exercises the changed behavior before push.
- Prefer focused unit/integration tests, targeted typecheck/lint commands, and affected-file
  checks. Do not automatically run the repository's full QA suite locally.
- Backend focused pattern when the local environment supports it:
  `bash -c 'set -a; source .env.test; set +a; .venv/bin/python -m pytest -o addopts= <focused-tests> -q'`
- Frontend default: run the focused test file(s) or test pattern plus targeted typecheck or
  lint when practical. The full frontend E2E suite belongs to CI by default.
- Run local E2E only when at least one is true: the linked acceptance criteria explicitly
  require local browser evidence; the change directly modifies E2E infrastructure or a
  critical browser-only flow; a focused local E2E spec is the fastest reproduction; or CI
  logs identify an E2E-specific failure that cannot be diagnosed from logs and code alone.
- Even then, run the narrowest relevant spec or project first. Do not launch the entire
  30+ minute E2E/QA matrix merely as ceremony.
- Josh explicitly permits CI-assisted debugging. A grounded repair may be pushed after
  focused validation, then the factory must wait for CI, inspect exact failures, and repair
  iteratively. Never represent CI-only validation as local validation.
- Never use `noqa`, type ignores, linter suppression, `--no-verify`, hook bypasses, or
  knowingly unrelated edits.
- Prepare one coherent repair and normally push one clean commit. Additional commits are
  acceptable when each is grounded in new CI evidence rather than speculative remote edits.

EVIDENCE MUST MATCH THE CLAIM
Use this taxonomy when reviewing, repairing, and writing PR bodies:

| Claim | Required evidence |
| Contract shape | schema tests, authenticated route-response tests, exact key assertions, OpenAPI checks |
| Payload size | representative serialized byte measurements before/after |
| Query reduction | query-count instrumentation before/after at named sizes |
| Latency improvement | controlled benchmark with cold/warm context and variance |
| UI behavior | focused unit coverage plus browser or explicit manual validation when required |
| Ownership/security | unauthorized and cross-user route tests |
| Cache behavior | dedupe, hit/miss, invalidation, rollback, cancellation, and stale-response tests |
| Pagination/scale | boundary, duplicate/gap, stale-cursor, and growth-size tests |

Field-count evidence proves contract narrowing only. It does not prove byte reduction,
query reduction, latency, or memory improvement. Do not demand a performance benchmark
from an honest stage that claims only naming or contract narrowing. Do not retain a
performance claim without the matching evidence.

HONEST STAGE FAST PATH
For an explicit staged slice, review only:
- the declared stage claims;
- invariants and compatibility affected by the diff;
- truthful stage/remaining-work metadata;
- tests and evidence appropriate to those claims.

Do not block a stage on parent-issue work clearly listed under Remaining work unless the
current diff makes that future work harder, unsafe, incompatible, or misleading. A stage
must use `Part of #N` or a plain reference, never a closure keyword, and must include
`Stage scope` and `Remaining work`. Repair dishonest metadata in the same lifecycle.

STRICT REVIEW OUTPUT
When the current SHA needs no repair and completed required CI is green, submit COMMENT
anchored to that SHA containing:

### Contract
- linked issue(s);
- complete issue or explicit staged slice;
- closure keyword yes/no;
- scope/dependency verdict.

### Acceptance criteria
One row for every full-issue criterion, or every declared stage claim plus affected
invariants for an honest stage:
`| # | Criterion | Status | Evidence |`
Statuses: PASS, FAIL, UNPROVEN, NOT APPLICABLE.
FAIL and UNPROVEN block, but repair-first applies before posting changes-required.
NOT APPLICABLE requires precise issue-grounded justification.

### Scope audit
Account for every changed file. Unrelated skills, generated noise, branch contamination,
or unexplained contract widening must be removed or justified.

### Findings
Behavioral, correctness, ownership/security, duplicate/empty/missing/stale/cross-user,
concurrency/cancellation/cache/transaction, compatibility, required measurement, and
regression-test findings are never cosmetic.

Post changes-required only when safe local repair cannot be completed in this target
lifecycle due to human judgment, unavailable required evidence, external/unwritable
branch, tooling failure, excessive coherent scope, failed local validation, or attempt
ceiling. State the exact blocker and executable next action.

FRESH-SHA SELF-REVIEW AFTER EVERY PUSH
Immediately after push, re-fetch the new SHA and full diff and audit:
- unintended files or branch contamination;
- correctness of every new/changed test;
- closure/staging language and measurement claims;
- unresolved feedback and changed contracts;
- required check set and branch mergeability.

Do not declare success merely because the push completed. If self-review finds a local
mistake and the fix lease remains yours, repair and validate before the coherent target
lifecycle ends, subject to the two-attempt ceiling.

CI WAIT AND DEBUG LOOP
After a grounded push:
- wait for required checks using timers, `gh` watch commands, or bounded polling. Keep the
  same target ownership while waiting instead of abandoning it because CI is pending.
- Use roughly 30-60 second polling intervals. Avoid hot loops.
- The default expensive full QA/E2E matrix runs in CI, not locally.
- Never modify code merely because checks are pending.
- If a branch-caused check fails, fetch the complete job logs, identify the exact failing
  command and evidence, make the smallest coherent repair, push, and wait again.
- CI-assisted debugging is permitted. Each iteration must be grounded in logs, code, tests,
  or the linked contract. Never spray speculative edits at the pipeline.
- If the execution environment imposes a hard runtime limit before CI completes, post a
  progress marker and concise state summary so the next heartbeat resumes the same target.
- If checks pass, perform a fresh strict review of the new SHA. When all evidence is
  satisfied, post v2 pass and ready in the SAME lifecycle.
- Never rubber-stamp. The post-push review must use the new full diff and exact checks.

INTEGRATION / READY
A PR is ready only when exact-SHA required checks are green, a complete strict-v2 pass
exists, no current-SHA blocker/needs-human exists, no actionable unresolved thread
remains, staging/closure is truthful, scope is clean, linked contract is satisfied, and
the branch is conflict-free. Post the ready marker. Never create or convert a draft PR unless Josh explicitly
requested a draft. Never merge.

RECOVERY
- Prefer resuming a coherent PR fix or implementation over selecting new work.
- Review/fix leases become resumable after their stated expiry with no branch movement.
- An issue implementation claim is resumable after 60 minutes without branch movement,
  progress marker, issue activity, or open PR. Do not freeze a lane for three hours.
- Re-check every fact and preserve the branch for audit.

IMPLEMENTATION
Prefer the #687 performance campaign, then fall back to any other eligible pending
ralph-task when no #687 task is executable this heartbeat (the #687 queue is empty,
blocked, or the next #687 task exceeds one bounded target lifecycle). Require
`ralph-task` and `ralph-status:pending` for every candidate; obey earliest incomplete
wave, priority, issue-number tie-break, dependencies, conflicts, and maximum four
substantial branches. For non-#687 fallback tasks, wave ordering does not apply;
select by priority, then issue-number tie-break, still honoring dependencies,
conflicts, lane limits, and the bounded-target-lifecycle rule. Use `make next-task`
for the primary #687 selection; when it returns a #687 task that exceeds one bounded
target lifecycle, list the remaining eligible pending ralph-tasks (e.g. via
`gh issue list --label ralph-task --label ralph-status:pending`) and pick the highest
eligible non-#687 one the same way. Claim atomically on `factory/<issue>-<slug>` from
current main and post worker, timestamp, environment, primary files, and attempt.
Enumerate criteria and matching evidence before coding. Implement the full issue unless
a valid staged slice is independently useful. Add mapped tests and every issue-required
measurement, run focused local validation when useful, self-audit the final diff, and
open a truthful non-draft PR. Let CI run the expensive full matrix, wait for it with timers,
debug grounded failures, and continue that same target toward green strict pass and ready.

GLOBAL RULES
- Existing work outranks new work.
- Never broaden scope or merge. CI-assisted debugging is allowed when grounded in exact
  logs and contract evidence. Do not confuse CI evidence with local evidence.
- Preserve auth, ownership, CSRF, accessibility, mobile behavior, exact contracts,
  transactions, caching, and unrelated user work.
- Never equate green CI with issue completion.
- Never manufacture a blocking review merely to avoid idle.
- Work on only one target PR or issue per heartbeat, but progress it through multiple
  safe states.

TERMINAL RESULT
The final line must be exactly one of:
FACTORY_RESULT: changed
FACTORY_RESULT: idle
FACTORY_RESULT: needs-human

Use changed after a verifiable branch or GitHub action. Use idle when no eligible target
exists, including all remaining PRs waiting on CI or human merge. Use needs-human only
for genuine judgment/tooling/evidence blockers.
PROMPT
)"
FACTORY_PROMPT="${FACTORY_PROMPT//__WORKER_ID__/$WORKER_ID}"

printf 'ComicPile local factory v7 (canonical policy, CI-driven QA)\n'
printf '  Source repo: %s\n' "$SOURCE_REPO"
printf '  Worktree:    %s\n' "$WORKTREE"
printf '  Model:       %s\n' "$MODEL"
printf '  Agent:       %s\n' "${AGENT:-<default>}"
printf '  Mode:        %s\n' "$MODE"
printf '  Run once:    %s\n' "$([[ "$RUN_ONCE" == "1" ]] && printf yes || printf no)"
printf '  Worker ID:   %s\n' "$WORKER_ID"

report_counts() {
  local open_prs open_issues pending_campaign
  open_prs="$(gh pr list --repo JoshCLWren/comic-pile --state open --limit 1000 --json number --jq 'length' 2>/dev/null || printf '?')"
  open_issues="$(gh issue list --repo JoshCLWren/comic-pile --state open --limit 1000 --json number --jq 'length' 2>/dev/null || printf '?')"
  pending_campaign="$(gh issue list --repo JoshCLWren/comic-pile --state open --limit 1000 --label ralph-task --label ralph-status:pending --json number --jq 'length' 2>/dev/null || printf '?')"
  printf '  GitHub queue: %s open PR(s), %s open issue(s), %s pending ralph task(s)\n'     "$open_prs" "$open_issues" "$pending_campaign"
}

report_counts

consecutive_failures=0
heartbeat=0

while true; do
  heartbeat=$((heartbeat + 1))
  timestamp="$(date +%Y%m%d_%H%M%S)"
  log_file="$WORKTREE/.opencode_logs/factory_${timestamp}_heartbeat_${heartbeat}.log"

  printf '\n[%s] Starting heartbeat %d\n' "$(date --iso-8601=seconds)" "$heartbeat"

  opencode_args=(
    run
    -m "$MODEL"
    --dir "$WORKTREE"
    --title "ComicPile factory heartbeat ${timestamp}"
  )

  [[ -n "$AGENT" ]] && opencode_args+=(--agent "$AGENT")
  [[ "$USE_AUTO" == "1" ]] && opencode_args+=(--auto)

  set +e
  opencode "${opencode_args[@]}" "$FACTORY_PROMPT" 2>&1 | tee "$log_file"
  opencode_status=${PIPESTATUS[0]}
  set -e

  if ((opencode_status != 0)); then
    consecutive_failures=$((consecutive_failures + 1))
    printf 'Heartbeat failed with status %d (%d/%d): %s\n' \
      "$opencode_status" "$consecutive_failures" "$MAX_FAILURES" "$log_file" >&2

    ((consecutive_failures < MAX_FAILURES)) \
      || die "stopping after $consecutive_failures consecutive OpenCode failures"

    sleep "$FAILURE_BACKOFF_SECONDS"
    continue
  fi

  if grep -Fq 'FACTORY_RESULT: needs-human' "$log_file"; then
    printf 'Factory needs human judgment. See %s\n' "$log_file" >&2
    exit 2
  fi

  if grep -Fq 'FACTORY_RESULT: changed' "$log_file"; then
    consecutive_failures=0
    report_counts
    if ((RUN_ONCE == 1)); then
      printf 'One-heartbeat mode completed after making progress.\n'
      exit 0
    fi
    printf 'Heartbeat made progress. Starting the next heartbeat immediately.\n'
    sleep 1
    continue
  fi

  if grep -Fq 'FACTORY_RESULT: idle' "$log_file"; then
    consecutive_failures=0
    report_counts
    if ((RUN_ONCE == 1)) || [[ "$MODE" == "drain" ]]; then
      printf 'Factory is currently idle. Stopping cleanly.\n'
      exit 0
    fi

    printf 'Factory is idle or waiting on CI. Checking again in %s seconds.\n' "$IDLE_SECONDS"
    sleep "$IDLE_SECONDS"
    continue
  fi

  consecutive_failures=$((consecutive_failures + 1))
  printf 'Heartbeat returned no terminal marker (%d/%d): %s\n' \
    "$consecutive_failures" "$MAX_FAILURES" "$log_file" >&2

  ((consecutive_failures < MAX_FAILURES)) \
    || die "stopping because OpenCode repeatedly omitted its terminal result marker"

  sleep "$FAILURE_BACKOFF_SECONDS"
done
