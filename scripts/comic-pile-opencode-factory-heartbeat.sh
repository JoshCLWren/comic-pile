#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_REPO="${COMIC_PILE_REPO:-/mnt/extra/josh/code/comic-pile}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE="${COMIC_PILE_FACTORY_WORKTREE:-}"
STATE_DIR="${COMIC_PILE_FACTORY_STATE_DIR:-${SOURCE_REPO%/}-factory-state}"
MANIFEST_HELPER="$SCRIPT_DIR/opencode-model-manifest.sh"
DEFAULT_MODEL="${COMIC_PILE_DEFAULT_MODEL:-deepseek/deepseek-v4-flash}"
MODEL=""
AGENT="${OPENCODE_AGENT:-}"
USE_AUTO="${OPENCODE_AUTO:-1}"
HEARTBEAT_TIMEOUT="${FACTORY_HEARTBEAT_TIMEOUT:-60}"
IDLE_SECONDS="${FACTORY_IDLE_SECONDS:-10}"
FAILURE_BACKOFF_SECONDS="${FACTORY_FAILURE_BACKOFF_SECONDS:-0}"
MAX_FAILURES="${FACTORY_MAX_FAILURES:-2}"
WAIT_FOR_SCOUT="${COMIC_PILE_FACTORY_WAIT_FOR_SCOUT:-0}"
SCOUT_READY_FILE="${COMIC_PILE_FACTORY_SCOUT_READY_FILE:-$STATE_DIR/scout-initial-pass.done}"
SCOUT_PID_FILE="${COMIC_PILE_FACTORY_SCOUT_PID_FILE:-}"
WORKER_ID="${OPENCODE_FACTORY_WORKER_ID:-local-opencode-${HOSTNAME:-host}}"
WORKER_ID="${WORKER_ID//[^a-zA-Z0-9._-]/-}"
MODE="drain"
RUN_ONCE=0

usage() {
  cat <<'USAGE'
Usage: comic-pile-opencode-factory.sh [options]

Options:
  --watch             Stay alive and poll while idle or waiting on CI.
  --once              Run exactly one factory heartbeat.
  --repo PATH         Source comic-pile repository.
  --worktree PATH     Dedicated factory worktree.
  --state-dir PATH    Factory state directory (manifest, heartbeats, scout).
  --model ID          OpenCode model id (default: rotate confirmed models).
  --agent NAME        Optional OpenCode agent name.
  --idle-seconds N    Watch-mode idle poll interval.
  --worker-id ID      Durable GitHub lease identity.
  -h, --help          Show this help.
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
    --watch) MODE="watch"; shift ;;
    --once) RUN_ONCE=1; shift ;;
    --repo) (($# >= 2)) || die "--repo requires a path"; SOURCE_REPO="$2"; shift 2 ;;
    --worktree) (($# >= 2)) || die "--worktree requires a path"; WORKTREE="$2"; shift 2 ;;
    --state-dir) (($# >= 2)) || die "--state-dir requires a path"; STATE_DIR="$2"; shift 2 ;;
    --model) (($# >= 2)) || die "--model requires an id"; MODEL="$2"; shift 2 ;;
    --agent) (($# >= 2)) || die "--agent requires a name"; AGENT="$2"; shift 2 ;;
    --idle-seconds) (($# >= 2)) || die "--idle-seconds requires a number"; IDLE_SECONDS="$2"; shift 2 ;;
    --worker-id)
      (($# >= 2)) || die "--worker-id requires a value"
      WORKER_ID="$2"
      WORKER_ID="${WORKER_ID//[^a-zA-Z0-9._-]/-}"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ -n "$WORKTREE" ]] || WORKTREE="${SOURCE_REPO%/}-factory"
is_nonnegative_integer "$IDLE_SECONDS" || die "FACTORY_IDLE_SECONDS must be an integer"
is_nonnegative_integer "$FAILURE_BACKOFF_SECONDS" || die "FACTORY_FAILURE_BACKOFF_SECONDS must be an integer"
is_nonnegative_integer "$MAX_FAILURES" || die "FACTORY_MAX_FAILURES must be an integer"
((MAX_FAILURES >= 1)) || die "FACTORY_MAX_FAILURES must be at least 1"
[[ "$HEARTBEAT_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die "FACTORY_HEARTBEAT_TIMEOUT must be a positive integer"

for command in git gh opencode flock tee grep date sleep stat tail touch setsid; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

git -C "$SOURCE_REPO" rev-parse --show-toplevel >/dev/null 2>&1 || die "not a Git repository: $SOURCE_REPO"
gh auth status >/dev/null 2>&1 || die "GitHub CLI is not authenticated; run: gh auth login"

[[ -x "$MANIFEST_HELPER" ]] || die "manifest helper is not executable: $MANIFEST_HELPER"
mkdir -p "$STATE_DIR"
"$MANIFEST_HELPER" init "$STATE_DIR"

if [[ "$WAIT_FOR_SCOUT" == "1" ]]; then
  printf 'Waiting for the model scout to complete its initial pass...\n'
  while [[ ! -f "$SCOUT_READY_FILE" ]]; do
    if [[ -n "$SCOUT_PID_FILE" && -f "$SCOUT_PID_FILE" ]]; then
      scout_pid="$(cat "$SCOUT_PID_FILE" 2>/dev/null || true)"
      if [[ "$scout_pid" =~ ^[0-9]+$ ]] && ! kill -0 -- "-$scout_pid" 2>/dev/null; then
        die "model scout exited before completing its initial pass"
      fi
    fi
    sleep 2
  done
  printf 'Model scout initial pass complete; using the confirmed-model manifest.\n'
fi

if [[ -z "$MODEL" ]]; then
  if [[ -n "${OPENCODE_MODEL:-}" ]]; then
    MODEL="$OPENCODE_MODEL"
  else
    MODEL="$("$MANIFEST_HELPER" next "$DEFAULT_MODEL" "$STATE_DIR")"
    printf 'Rotating to model from manifest: %s\n' "$MODEL" >&2
  fi
fi
export OPENCODE_MODEL="$MODEL"

if ! opencode models 2>/dev/null | grep -Fq "$MODEL"; then
  die "configured model was not found in opencode models: $MODEL"
fi

if ! git -C "$WORKTREE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'Creating dedicated factory worktree: %s\n' "$WORKTREE"
  git -C "$SOURCE_REPO" fetch --prune origin
  mkdir -p "$(dirname "$WORKTREE")"
  git -C "$SOURCE_REPO" worktree add --detach "$WORKTREE" origin/main
fi

mkdir -p "$WORKTREE/.opencode_logs" "$WORKTREE/.opencode_handoff"
exec 9>"$WORKTREE/.comic-pile-factory.lock"
flock -n 9 || die "another local factory process already holds the factory lock"

# Every heartbeat runs against a fresh origin/main checkout so merged factory
# tooling and policy land before the next heartbeat selects work. Without this a
# long-lived worktree silently goes stale after each merge to main.
printf 'Refreshing factory worktree to latest origin/main...\n'
git -C "$SOURCE_REPO" fetch --prune origin
git -C "$WORKTREE" switch -f --detach origin/main
printf 'Factory worktree is now at %s (%s).\n' \
  "$(git -C "$WORKTREE" rev-parse --short origin/main)" "$(git -C "$WORKTREE" log -1 --format='%s' origin/main)"

FACTORY_PROMPT="$(cat <<'PROMPT'
Act as one high-ownership local factory heartbeat for JoshCLWren/comic-pile.
Durable worker ID: `__WORKER_ID__`.

Read current-main AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, and
`docs/AUTONOMOUS_FACTORY_POLICY.md` before selection. The canonical factory policy wins
when any older or generic instruction conflicts.

MISSION
Drive the open issue backlog to zero. Success means issues truthfully closed and defects
removed, not PR count, comments, commits, reviews, labels, or hours spent.

CONTINUOUS CYCLE
1. Drain every executable issue except deferred backlog-zero checkpoint #679.
2. When #679 is the only remaining executable checkpoint, restore the complete maintained
   Chromium Playwright E2E suite.
3. Create one GitHub issue per independent reproducible Chromium product defect with failure
   evidence and the `bug` label.
4. Resume draining the replenished backlog immediately.
5. Preserve `user-reported` only for bugs actually reported by a user.

Firefox and WebKit are optional diagnostics for browser-specific investigations. They are
not required factory release coverage and must not delay issue closure or merges.

SELECTION ORDER
Before choosing work, enumerate current open PRs, current review threads, leases, and open
issues. Select exactly in this order:
1. A branch-caused failing check, conflict, or actionable review finding that currently
   prevents an active implementation PR from becoming mergeable.
2. The newest unclaimed open issue labeled both `user-reported` and `bug`.
3. The highest-priority unclaimed reproducible E2E-discovered `bug` issue.
4. The highest-value unclaimed executable issue, honoring priorities and dependencies while
   excluding #679 until every other executable issue is closed.
5. Existing PR work only when required to complete its issue contract or make it mergeable.
6. Factory maintenance only when factory behavior blocks issue delivery.

CONCURRENCY
At most one implementation worker owns an issue unless workers explicitly declare
non-overlapping file ownership. Once another worker holds the highest-priority issue, choose
the next eligible issue. When fewer than four substantive implementation PRs are open and
unclaimed executable issues exist, open a coherent implementation for a separate issue
instead of polishing an existing PR.

ANTI-ORBIT RULES
- Green, ready, review-passed, or merge-gated PRs are excluded from ordinary selection.
- Do not repeatedly debate, review, summarize, or embellish the same few PRs.
- Do not add optional tests, cleanup, documentation, PR-body edits, evidence prose, or minor
  slices while higher-priority executable issues remain.
- Waiting for CI, review, merge, Josh, or external availability does not reserve the worker.
  Preserve context and select another free issue.
- Do not create replacement PRs merely because main advanced.
- Do not split one issue into avoidable foundation or stage PRs. Implement the full contract
  in one coherent non-draft PR whenever reasonably reviewable.

REVIEW FEEDBACK IS WORK
Before pass, ready, merge-gated, or any claim that no blocking correctness issue remains:
- fetch all current-SHA review submissions and inline review threads;
- ignore only status noise, summaries, release notes, rate-limit notices, and optional
  finishing-touch advertisements;
- classify every actionable finding as fixed, demonstrably outdated by a specific later
  change, or rebutted once with concrete evidence;
- respond to or resolve every actionable current thread;
- refuse readiness or merge while an unresolved actionable correctness, security,
  ownership, data-integrity, migration, concurrency, recovery, or test-validity finding
  remains.
Your own review conclusion never silently overrides existing human or bot feedback.
Every push invalidates all prior review and gate conclusions.

GATED MERGES ARE AUTHORIZED
You may merge without asking again only when every gate is true for the exact current head:
- PR is open, non-draft, mergeable, and conflict-free;
- all required CI checks completed successfully;
- all actionable current review findings are accounted for;
- focused validation or exact-head CI establishes the required evidence;
- declared PR scope is complete and truthful;
- merge is safe for ownership, migrations, deployment, security, and data;
- merge method is allowed by repository settings;
- pass the exact expected head SHA to the merge operation.
Never enable auto-merge. Never merge a moved SHA. If any gate cannot be verified, repair the
branch or select other work. After merge, verify issue closure and continue remaining issue
work if the issue did not truthfully close.

WORK LOOP
`inspect issue -> claim -> implement closure-critical behavior -> focused test -> commit ->
push -> inspect exact SHA and CI -> inspect all review feedback -> repair -> revalidate ->
merge when gated -> verify issue closure`

A normal heartbeat while executable work exists must push substantive code/tests/migration,
repair a blocking defect/conflict/review finding, open a coherent non-draft implementation
PR, perform a fully gated exact-head merge, create evidence-backed Chromium bug issues during
the backlog-zero phase, or repair factory code that blocks delivery. Comments, labels,
claims, reviews, PR-body edits, and ready markers alone do not count.

BACKLOG-ZERO CHROMIUM PHASE
Issue #679 is deferred and excluded from ordinary executable selection while any other
executable issue remains open. Once all other executable issues are closed, restore and run
the maintained Chromium suite, distinguish product failures from infrastructure failures,
create one focused `bug` issue per independent reproducible product defect, and resume
normal backlog draining. Firefox and WebKit are optional diagnostics, not completion gates.

REPOSITORY SAFETY
- Never push directly to main.
- Never create or convert a draft PR unless Josh explicitly requested it.
- Never enable auto-merge.
- Never weaken or bypass checks, remove meaningful coverage, use suppressions to fake green,
  or manufacture evidence.
- Never mutate schedules or factory topology.

TOOLING GATE
Confirm checkout, focused tests, commit, push, GitHub reads/writes, review-thread access,
CI-log access, and merge access. Print:
`FACTORY_TOOLING: local-checkout=yes focused-tests=yes ci-debug=yes commit=yes push=yes review-threads=yes merge=yes`
Never claim a command ran unless it ran.

LEASE MARKERS
Issue claim:
`<!-- comic-pile-factory-implement-claim-v3:issue-<n>:<worker-id>:<epoch>:attempt-<n> -->`
Issue progress:
`<!-- comic-pile-factory-implement-progress-v3:issue-<n>:<worker-id>:<epoch> -->`
Review claim:
`<!-- comic-pile-factory-review-claim-v2:<sha>:<worker-id>:<epoch> -->`
Verdicts:
`<!-- comic-pile-factory-review-v2:<sha>:pass -->`
`<!-- comic-pile-factory-review-v2:<sha>:changes-required -->`
Fix claim:
`<!-- comic-pile-factory-fix-claim-v3:<sha>:<worker-id>:<epoch>:attempt-<n> -->`
Fix progress:
`<!-- comic-pile-factory-fix-progress-v3:<sha>:<worker-id>:<epoch> -->`
Ready:
`<!-- comic-pile-factory-ready-v2:<sha> -->`
Needs human:
`<!-- comic-pile-factory-needs-human-v2:<sha-or-issue> -->`
Released:
`<!-- comic-pile-factory-claim-released-v3:<target>:<worker-id>:<epoch>:<reason> -->`

MODEL SIGNING
The model running this heartbeat is `__MODEL_ID__`. Sign PR bodies you open or update with:
`Model: __MODEL_ID__`

STOP CONDITIONS
Stop only when no executable work exists outside the deferred #679 Chromium cycle, Josh
redirects the work, a genuine human-only irreversible/product/credential decision is
required, all safe write paths fail, or an evidence-grounded repair ceiling is reached.

TERMINAL RESULT
The final line must be exactly one of:
FACTORY_RESULT: changed
FACTORY_RESULT: idle
FACTORY_RESULT: needs-human
PROMPT
)"

FACTORY_PROMPT="${FACTORY_PROMPT//__WORKER_ID__/$WORKER_ID}"
FACTORY_PROMPT="${FACTORY_PROMPT//__MODEL_ID__/$MODEL}"

printf 'ComicPile local factory v16 (backlog-drain and gated-merge)\n'
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
  printf '  GitHub queue: %s open PR(s), %s open issue(s), %s pending ralph task(s)\n' "$open_prs" "$open_issues" "$pending_campaign"
}

report_counts
consecutive_failures=0
heartbeat=0

while true; do
  heartbeat=$((heartbeat + 1))
  timestamp="$(date +%Y%m%d_%H%M%S)"
  log_file="$WORKTREE/.opencode_logs/factory_${timestamp}_heartbeat_${heartbeat}.log"
  printf '\n[%s] Starting heartbeat %d (model %s)\n' "$(date --iso-8601=seconds)" "$heartbeat" "$MODEL"

  opencode_args=(run -m "$MODEL" --dir "$WORKTREE" --title "ComicPile factory heartbeat ${timestamp}")
  [[ -n "$AGENT" ]] && opencode_args+=(--agent "$AGENT")
  [[ "$USE_AUTO" == "1" ]] && opencode_args+=(--auto)

  hb_file="$STATE_DIR/heartbeats/factory_heartbeat_${heartbeat}.hb"
  mkdir -p "$STATE_DIR/heartbeats"
  touch "$hb_file"

  set +e
  setsid bash -c '
    LOG="$1"; HB="$2"; shift 2
    opencode "$@" 2>&1 | while IFS= read -r line; do
      touch "$HB"
      printf "%s\n" "$line"
    done | tee "$LOG"
    exit "${PIPESTATUS[0]}"
  ' _ "$log_file" "$hb_file" "${opencode_args[@]}" "$FACTORY_PROMPT" &
  run_pid=$!
  (
    while kill -0 "$run_pid" 2>/dev/null; do
      age=$(( $(date +%s) - $(stat -c %Y "$hb_file" 2>/dev/null || printf '%s' "$(date +%s)") ))
      if grep -Eiq 'Tokens per minute limit exceeded|too many tokens processed' "$log_file" 2>/dev/null; then
        printf 'WATCHDOG: stopping heartbeat %d immediately after token-per-minute limit.\n' "$heartbeat" >&2
        kill -TERM -- "-$run_pid" 2>/dev/null || kill -TERM "$run_pid" 2>/dev/null || true
        sleep 1
        kill -KILL -- "-$run_pid" 2>/dev/null || kill -KILL "$run_pid" 2>/dev/null || true
        break
      fi
      if ((age > HEARTBEAT_TIMEOUT)); then
        printf 'WATCHDOG: killing heartbeat %d run %s because no output arrived for %ss\n' "$heartbeat" "$run_pid" "$age" >&2
        kill -9 -- "-$run_pid" 2>/dev/null || kill -9 "$run_pid" 2>/dev/null || true
        break
      fi
      sleep 1
    done
  ) &
  watchdog_pid=$!
  wait "$run_pid"
  opencode_status=$?
  kill "$watchdog_pid" 2>/dev/null || true
  set -e

  if ((opencode_status == 0)); then
    if ! "$MANIFEST_HELPER" record "$MODEL" "$STATE_DIR" >/dev/null 2>&1; then
      consecutive_failures=$((consecutive_failures + 1))
      printf 'Heartbeat succeeded but failed to record model usage (%d/%d): %s\n' "$consecutive_failures" "$MAX_FAILURES" "$log_file" >&2
      ((consecutive_failures < MAX_FAILURES)) || die "stopping after $consecutive_failures consecutive OpenCode failures"
      sleep "$FAILURE_BACKOFF_SECONDS"
      continue
    fi
  fi

  if ((opencode_status != 0)); then
    consecutive_failures=$((consecutive_failures + 1))
    printf 'Heartbeat failed with status %d (%d/%d): %s\n' "$opencode_status" "$consecutive_failures" "$MAX_FAILURES" "$log_file" >&2
    ((consecutive_failures < MAX_FAILURES)) || die "stopping after $consecutive_failures consecutive OpenCode failures"
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
  printf 'Heartbeat returned no terminal marker (%d/%d): %s\n' "$consecutive_failures" "$MAX_FAILURES" "$log_file" >&2
  ((consecutive_failures < MAX_FAILURES)) || die "stopping because OpenCode repeatedly omitted its terminal result marker"
  sleep "$FAILURE_BACKOFF_SECONDS"
done
