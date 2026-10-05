#!/usr/bin/env bash
# Resolve the credential for factory push and pull-request creation.
# Worker 48 uses its GitHub App installation token when configured.
# Every other worker prints PR_REBASE_TOKEN. Never creates a GitHub App.
set -Eeuo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$here/factory_worker_github_app.py" "$@"
