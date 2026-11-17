#!/usr/bin/env bash
# Count GitHub CLI requests made by a factory job, then run the real gh.
#
# The whole repository shares one Actions installation REST budget. This
# meter records one line per invocation (epoch, normalized command) in
# FACTORY_GH_CALL_LOG so factory_gh_usage.py can report which callers spend
# it. It never logs arguments that could carry secrets or bodies.
factory_gh_meter_record() {
  [[ -n "${FACTORY_GH_CALL_LOG:-}" ]] || return 0
  local group="${1:-}" name="${2:-}" key method='' paginate='' fields=0 arg
  if [[ "$group" == api ]]; then
    shift
    key=''
    while (( $# )); do
      arg="$1"
      case "$arg" in
        -X|--method) method="${2:-GET}"; shift 2; continue ;;
        --method=*) method="${arg#--method=}" ;;
        --paginate) paginate=' paginate' ;;
        -f|-F|--field|--raw-field|--input) fields=1; shift 2; continue ;;
        -H|--header|--jq|-q|--template|-t|--cache|--hostname|--preview|-p)
          shift 2; continue ;;
        -*) ;;
        *) [[ -n "$key" ]] || key="$arg" ;;
      esac
      shift
    done
    # Drop query strings and replace ids/SHAs so endpoints aggregate.
    key="${key%%\?*}"
    key="$(sed -E 's#^/##; s#repos/[^/]+/[^/]+#repos/R#; s#/[0-9a-f]{40}#/SHA#g; s#/[0-9]+#/N#g' <<< "$key")"
    # gh defaults to POST when fields are given without an explicit method.
    [[ -n "$method" ]] || { (( fields )) && method=POST || method=GET; }
    key="api ${method^^} ${key}${paginate}"
  else
    key="gh ${group} ${name}"
  fi
  printf '%s\t%s\n' "$(date +%s)" "$key" >> "$FACTORY_GH_CALL_LOG" 2>/dev/null || true
}

# True for gh invocations that only read GitHub state. Those may use the
# optional read-only factory App token (a separate 5000/h installation bucket)
# instead of the repository's shared GITHUB_TOKEN budget. Writes always keep
# the workflow token so they never trigger additional workflows.
factory_gh_is_read() {
  local group="${1:-}" name="${2:-}" arg
  case "$group" in
    api)
      shift
      [[ "${1:-}" != graphql ]] || return 1
      for arg in "$@"; do
        case "$arg" in
          -X|--method|--method=*|-f|-F|--field|--raw-field|--input|-f*|-F*) return 1 ;;
        esac
      done
      return 0 ;;
    pr) [[ "$name" =~ ^(list|view|checks|diff|status)$ ]] ;;
    issue) [[ "$name" =~ ^(list|view|status)$ ]] ;;
    run) [[ "$name" =~ ^(list|view)$ ]] ;;
    repo|release|workflow) [[ "$name" =~ ^(list|view)$ ]] ;;
    *) return 1 ;;
  esac
}

# Run the real gh, using the read-only token for pure reads when configured.
factory_gh_real() {
  local real="${FACTORY_REAL_GH:-/usr/bin/gh}"
  # Installation tokens expire after an hour; long sessions fall back.
  if [[ -n "${FACTORY_READ_TOKEN:-}" ]] \
    && (( $(date +%s) < ${FACTORY_READ_TOKEN_EXPIRES:-0} )) \
    && factory_gh_is_read "$@"; then
    GH_TOKEN="$FACTORY_READ_TOKEN" "$real" "$@"
  else
    "$real" "$@"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  factory_gh_meter_record "$@"
  factory_gh_real "$@"
fi
