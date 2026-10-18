#!/usr/bin/env bash
# Dispatch Deploy Production after a factory bot merge.
#
# A merge made with the built-in GITHUB_TOKEN (github-actions[bot]) does not
# fire push or workflow_run events, so Deploy Production never starts for it,
# and its */5 cron fires only every few hours in practice. workflow_dispatch is
# the one event GITHUB_TOKEN may raise, so every bot-merge path calls this
# helper after merging. Drains call it once per run, after the last merge.
#
# The dispatch passes source=factory-merge, which makes Deploy Production
# deduplicate against a READY deployment of the same main SHA (a manual
# dispatch still forces a redeploy). The vercel-production concurrency group
# (cancel-in-progress: false) runs at most one deploy at a time and keeps only
# the newest pending run. Every run deploys current main, so overlapping
# dispatches cannot deploy an older SHA after a newer one.
#
# Failure is non-fatal: the merge already landed, and the next push, dispatch,
# or cron run deploys the same main. Needs `actions: write`.
# FACTORY_DEPLOY_DISPATCH=off disables it for an incident.

factory_dispatch_production_deploy() {
  local reason="${1:-factory bot merge}"
  local repo="${GITHUB_REPOSITORY:-JoshCLWren/comic-pile}"
  if [[ "${FACTORY_DEPLOY_DISPATCH:-on}" == 'off' ]]; then
    echo "Deploy Production dispatch disabled (FACTORY_DEPLOY_DISPATCH=off); skipping: ${reason}" >&2
    return 0
  fi
  if gh workflow run deploy-production.yml --repo "$repo" --ref main \
    -f source=factory-merge -f reason="$reason"; then
    echo "Dispatched Deploy Production on main: ${reason}"
  else
    echo "::warning::Unable to dispatch Deploy Production after ${reason}; the next push, dispatch, or cron run deploys main." >&2
  fi
  return 0
}
