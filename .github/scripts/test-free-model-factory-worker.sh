#!/usr/bin/env bash
set -Eeuo pipefail

worker='.github/scripts/free-model-factory-worker.sh'
validator='.github/scripts/validate-free-model-factories.py'

bash -n "$worker"
python "$validator"

# The fixed-model wrapper must use canonical claim/release markers and must not
# regress to branch-prefix ownership or direct execution of the #679 epic.
grep -q 'comic-pile-factory-implement-claim-v3' "$worker"
grep -q 'comic-pile-factory-claim-released-v3' "$worker"
grep -q 'issues/679/sub_issues' "$worker"
grep -q 'session-end-handoff' "$worker"
! grep -q 'choose_backlog_zero_issue' "$worker"
! grep -q -- '--arg prefix "factory/${WORKER}-"' "$worker"
! grep -q 'including #679; ending this session cleanly' "$worker"

printf 'Fixed-model worker lease and E2E fallback invariants passed.\n'
