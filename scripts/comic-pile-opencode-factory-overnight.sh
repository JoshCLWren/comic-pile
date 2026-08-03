#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_REPO="${COMIC_PILE_REPO:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
RUNNER="$SCRIPT_DIR/comic-pile-opencode-factory.sh"
STATE_DIR="${COMIC_PILE_FACTORY_STATE_DIR:-${SOURCE_REPO%/}-factory-state}"
PID_FILE="$STATE_DIR/overnight.pid"
SUPERVISOR_LOG="$STATE_DIR/overnight.log"
DEFAULT_MODEL="deepseek/deepseek-v4-flash"

usage() {
  cat <<'USAGE'
Usage: bash scripts/comic-pile-opencode-factory-overnight.sh <start|stop|status|run> [factory options]

Commands:
  start    Launch the continuous OpenCode factory in the background.
  stop     Stop the background factory and all of its child processes.
  status   Report whether the supervised factory is running.
  run      Run continuously in the foreground.

Environment defaults:
  OPENCODE_MODEL=deepseek/deepseek-v4-flash
  FACTORY_IDLE_SECONDS=60
  FACTORY_FAILURE_BACKOFF_SECONDS=30
  FACTORY_MAX_FAILURES=5

Additional arguments are passed to comic-pile-opencode-factory.sh after --watch.
Examples:
  bash scripts/comic-pile-opencode-factory-overnight.sh start
  bash scripts/comic-pile-opencode-factory-overnight.sh status
  bash scripts/comic-pile-opencode-factory-overnight.sh stop
  bash scripts/comic-pile-opencode-factory-overnight.sh run --idle-seconds 30
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

read_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$pid"
}

is_running() {
  local pid
  pid="$(read_pid)" || return 1
  kill -0 -- "-$pid" 2>/dev/null
}

cleanup_stale_pid() {
  if [[ -f "$PID_FILE" ]] && ! is_running; then
    rm -f "$PID_FILE"
  fi
}

run_factory() {
  export OPENCODE_MODEL="${OPENCODE_MODEL:-$DEFAULT_MODEL}"
  export FACTORY_IDLE_SECONDS="${FACTORY_IDLE_SECONDS:-60}"
  export FACTORY_FAILURE_BACKOFF_SECONDS="${FACTORY_FAILURE_BACKOFF_SECONDS:-30}"
  export FACTORY_MAX_FAILURES="${FACTORY_MAX_FAILURES:-5}"
  exec "$RUNNER" --watch "$@"
}

command="${1:-}"
[[ -n "$command" ]] || { usage; exit 2; }
shift

[[ -x "$RUNNER" ]] || die "factory runner is not executable: $RUNNER"
command -v setsid >/dev/null 2>&1 || die "required command not found: setsid"
mkdir -p "$STATE_DIR"
cleanup_stale_pid

case "$command" in
  start)
    if is_running; then
      printf 'ComicPile overnight factory is already running (process group %s).\n' "$(read_pid)"
      exit 0
    fi

    printf 'Starting ComicPile overnight factory with model %s. Supervisor log: %s\n' "${OPENCODE_MODEL:-$DEFAULT_MODEL}" "$SUPERVISOR_LOG"
    nohup setsid env \
      OPENCODE_MODEL="${OPENCODE_MODEL:-$DEFAULT_MODEL}" \
      FACTORY_IDLE_SECONDS="${FACTORY_IDLE_SECONDS:-60}" \
      FACTORY_FAILURE_BACKOFF_SECONDS="${FACTORY_FAILURE_BACKOFF_SECONDS:-30}" \
      FACTORY_MAX_FAILURES="${FACTORY_MAX_FAILURES:-5}" \
      "$RUNNER" --watch "$@" >>"$SUPERVISOR_LOG" 2>&1 &
    pid=$!
    printf '%s\n' "$pid" >"$PID_FILE"
    sleep 1

    if ! kill -0 -- "-$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      die "factory exited during startup; inspect $SUPERVISOR_LOG"
    fi

    printf 'ComicPile overnight factory started (process group %s).\n' "$pid"
    ;;

  stop)
    if ! is_running; then
      cleanup_stale_pid
      printf 'ComicPile overnight factory is not running.\n'
      exit 0
    fi

    pid="$(read_pid)"
    printf 'Stopping ComicPile overnight factory process group %s...\n' "$pid"
    kill -TERM -- "-$pid"

    for _ in {1..20}; do
      if ! kill -0 -- "-$pid" 2>/dev/null; then
        rm -f "$PID_FILE"
        printf 'ComicPile overnight factory stopped.\n'
        exit 0
      fi
      sleep 1
    done

    printf 'Factory did not stop after 20 seconds; sending SIGKILL to the process group.\n' >&2
    kill -KILL -- "-$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    ;;

  status)
    if is_running; then
      printf 'ComicPile overnight factory is running (process group %s).\n' "$(read_pid)"
      printf 'Supervisor log: %s\n' "$SUPERVISOR_LOG"
      exit 0
    fi

    cleanup_stale_pid
    printf 'ComicPile overnight factory is not running.\n'
    exit 1
    ;;

  run)
    run_factory "$@"
    ;;

  -h|--help|help)
    usage
    ;;

  *)
    usage >&2
    die "unknown command: $command"
    ;;
esac
