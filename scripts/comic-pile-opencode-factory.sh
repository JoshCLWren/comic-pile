#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_REPO="${COMIC_PILE_REPO:-/mnt/extra/josh/code/comic-pile}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE="${COMIC_PILE_FACTORY_WORKTREE:-}"
STATE_DIR="${COMIC_PILE_FACTORY_STATE_DIR:-${SOURCE_REPO%/}-factory-state}"
MANIFEST_HELPER="$SCRIPT_DIR/opencode-model-manifest.sh"
DEFAULT_MODEL="${COMIC_PILE_DEFAULT_MODEL:-deepseek/deepseek-v4-pro}"
MODEL=""
AGENT="${OPENCODE_AGENT:-}"
USE_AUTO="${OPENCODE_AUTO:-1}"
HEARTBEAT_TIMEOUT="${FACTORY_HEARTBEAT_TIMEOUT:-900}"
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

for command in git gh opencode flock tee grep date sleep stat tail touch setsid; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

git -C "$SOURCE_REPO" rev-parse --show-toplevel >/dev/null 2>&1 || die "not a Git repository: $SOURCE_REPO"
gh auth status >/dev/null 2>&1 || die "GitHub CLI is not authenticated; run: gh auth login"

[[ -x "$MANIFEST_HELPER" ]] || die "manifest helper is not executable: $MANIFEST_HELPER"
mkdir -p "$STATE_DIR"
"$MANIFEST_HELPER" init "$STATE_DIR"

# Select the model: explicit --model wins, then OPENCODE_MODEL, then rotation
# across confirmed models (round-robin), falling back to the default model.
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

FACTORY_PROMPT="$(cat <<'PROMPT'
Act as one high-ownership local heartbeat for JoshCLWren/comic-pile. Durable worker ID:
`__WORKER_ID__`.

Read AGENTS.md, docs/ISSUE_EXECUTION_PROTOCOL.md, and
`docs/AUTONOMOUS_FACTORY_POLICY.md` from current main before selecting or writing. The
canonical factory policy controls lifecycle behavior when generic guidance conflicts.

FINISH WHAT YOU START
Success is measured by issues closed, not pull requests opened. Own an issue until it is
closed or genuinely blocked by a human-only decision. A PR is only one state in the issue
lifecycle. Do not leave an issue merely because one PR is open, green, ready, or merged.
If executable work remains, continue it.

OWN AN ISSUE, NOT A PR
Prefer finishing already-started issues over starting new ones. Reconstruct GitHub state,
identify parent issues behind open and recently merged partial PRs, and select the shortest
path to truthful issue closure. Multiple workers may cooperate on one issue only with
non-overlapping file ownership and explicit coordination.

NO PLANNING PRS
Do not open planning-only, architecture-only, inventory-only, or implementation-plan PRs
unless the issue itself explicitly requests documentation. Planning belongs in scratch
work or issue comments. Documentation supports implementation; it is never a substitute
for executable work. Writing docs to avoid coding is a policy failure.

ONE COHERENT PR BY DEFAULT
Implement the full issue in one coherent PR whenever reasonably reviewable. Large coherent
PRs are allowed and preferred over chains of tiny foundation or stage PRs. Split only when
Josh requests it, a feature flag or independent deployment boundary requires it, unavoidable
branch collisions make one PR unsafe, review would genuinely become unreasonable, or a
destructive decision needs separate authorization. If split, retain issue ownership and
immediately continue the next required slice.

REPOSITORY SAFETY
- Never push directly to main.
- Never create or convert a draft PR unless Josh explicitly requested a draft.
- Never merge.
- Never enable auto-merge.
- Never weaken checks, skip tests, delete meaningful coverage, bypass hooks, or add
  suppressions merely to turn CI green.

TOOLING GATE
Confirm checkout, focused tests, commit, push, GitHub reads/writes, and CI-log access.
Print:
`FACTORY_TOOLING: local-checkout=yes focused-tests=yes ci-debug=yes commit=yes push=yes`
Never claim a command ran unless it ran. CI-assisted debugging is permitted.

SELECTION
Before selecting, enumerate open PRs and eligible issues. Prefer:
1. branch-caused failed CI or active repair on an already-owned issue;
2. executable remaining work needed to close an issue with an open or recently merged
   partial PR;
3. green PR needing strict review or repair;
4. ready PR awaiting Josh's explicit merge authorization;
5. highest-value unclaimed executable issue;
6. factory maintenance only when factory behavior blocks delivery.

Do not start a new issue while an owned issue has executable remaining work.

LIFECYCLE
Select issue -> claim issue -> implement full contract -> focused validation -> push ->
review -> escalate REVIEW -> FIX when needed -> CI debug loop -> fresh-SHA review -> ready
-> wait for explicit merge -> verify issue closure or continue remaining work.

PR creation, review completion, pending CI, green CI, ready, or one merged slice are not
stop conditions while the issue remains open and executable work remains.

DURABLE MARKERS AND LEASES
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

Review leases are active only for exact current SHA with age <=2700 seconds. Repair and
implementation leases are active with age <=3600 seconds after latest claim or progress.
Re-fetch before claiming. Lowest GitHub comment ID wins simultaneous races. A pushed new
SHA releases the old-SHA lease automatically. A merged PR does not release issue ownership
when the parent issue still has executable remaining work.

REPAIR FIRST
When review finds a bounded understood defect on a writable branch, claim and repair it in
the same issue lifecycle. CI failures, rebases, merge conflicts, test updates, review
defects, browser inconvenience, broad diffs, and needing to write more code are ordinary
engineering, not human blockers.

VALIDATION
Run the narrowest focused tests, lint, type checks, migration checks, or browser specs that
directly exercise the change. Let CI carry the expensive configured matrix. Inspect exact
failure logs and make evidence-grounded repairs. Never add ornamental tests only to move a
coverage percentage.

EVIDENCE
Green CI is necessary but not sufficient. Match claims with evidence for contracts, query
counts, payload bytes, latency, browser behavior, ownership, caching, migrations, and
scale. Never manufacture PASS. Missing optional evidence is not permission to replace
implementation with documentation.

STRICT REVIEW AND READY
Freshly review every new SHA. Account for the full issue contract, all changed files,
regressions, security, ownership, concurrency, failure behavior, unresolved threads, and
exact-SHA CI. A PR is ready only after strict pass, green required CI or a proven non-branch
exception, resolved actionable threads, coherent scope, truthful metadata, and no conflict.

DURABLE PROGRESS FLOOR
A normal heartbeat must commit and push code/tests/migrations, materially repair a branch,
resolve a conflict, open a coherent non-draft implementation PR, or repair factory code.
Comments, labels, claims, reviews, PR-body edits, and ready markers alone do not count.

OPENING A PR
Open a truthful non-draft PR that implements the full issue contract whenever reasonably
reviewable. Use a closure keyword only when merge will actually close the issue. Do not use
`Stage scope` and `Remaining work` as an excuse for avoidable splitting.

MODEL SIGNING
The agent id running this heartbeat is `__MODEL_ID__` (env OPENCODE_MODEL). Sign every PR
body you open or update with a trailing block:
`Model: __MODEL_ID__`
Your commits are already signed by the prepare-commit-msg hook; keep the PR body in sync so
model attribution is visible at a glance and usage stats stay truthful. Never claim a model
other than the one in OPENCODE_MODEL.

STOP CONDITIONS
Stop only when the owned issue is closed; Josh explicitly redirects it; a genuine human-only
product, credential, permission, destructive, external-access, or irreversible decision is
required; all safe write paths fail; or an evidence-grounded repair ceiling is reached.

TERMINAL RESULT
The final line must be exactly one of:
FACTORY_RESULT: changed
FACTORY_RESULT: idle
FACTORY_RESULT: needs-human
PROMPT
)"

# Model attribution: substitute the resolved model id so PR bodies are signed.
FACTORY_PROMPT="${FACTORY_PROMPT//__WORKER_ID__/$WORKER_ID}"
FACTORY_PROMPT="${FACTORY_PROMPT//__MODEL_ID__/$MODEL}"

printf 'ComicPile local factory v8 (closure-first issue ownership)\n'
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

  # Heartbeat file: touched on every line of opencode output so the watchdog can
  # kill a hung run that has not produced output for HEARTBEAT_TIMEOUT seconds.
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
  ( # Watchdog: kill the run's process group when the heartbeat goes stale.
    while kill -0 "$run_pid" 2>/dev/null; do
      age=$(( $(date +%s) - $(stat -c %Y "$hb_file" 2>/dev/null || printf '%s' "$(date +%s)") ))
      if ((age > HEARTBEAT_TIMEOUT)); then
        printf 'WATCHDOG: killing heartbeat %d run %s — no output for %ss\n' "$heartbeat" "$run_pid" "$age" >&2
        kill -9 -- "-$run_pid" 2>/dev/null || kill -9 "$run_pid" 2>/dev/null || true
        break
      fi
      sleep 10
    done
  ) &
  watchdog_pid=$!
  wait "$run_pid"
  opencode_status=$?
  kill "$watchdog_pid" 2>/dev/null || true
  set -e

  # Mark the model as used (confirmed) when the run completed successfully.
  if ((opencode_status == 0)); then
    "$MANIFEST_HELPER" record "$MODEL" "$STATE_DIR" >/dev/null 2>&1 || true
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
