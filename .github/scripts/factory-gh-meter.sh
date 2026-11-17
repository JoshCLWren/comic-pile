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

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  factory_gh_meter_record "$@"
  real="${FACTORY_REAL_GH:-/usr/bin/gh}"
  exec "$real" "$@"
fi
