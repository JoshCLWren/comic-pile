const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { spawnSync } = require('node:child_process');
const { test } = require('node:test');

const source = readFileSync('.github/scripts/free-model-factory-worker-primitives.sh', 'utf8');
const start = source.indexOf('persist_issue_pr() {');
const body = source.slice(start, source.indexOf('\n}\n', start) + 3);

function run(credential) {
  return spawnSync('bash', ['-c', `
    set -Eeuo pipefail
    EXPECTED_HEAD=base DISPLAY=test MODEL=test SOURCE=test WORKER_ID=test WORKER=11
    GH_TOKEN=workflow-token
    PR_REBASE_TOKEN="$1"
    reject_out_of_scope_diff() { return 0; }
    git() {
      case "$1" in
        status) printf changed ;;
        rev-parse|ls-remote) printf head ;;
      esac
    }
    gh() {
      if [[ "$1 $2" == 'issue view' ]]; then
        printf title
      elif [[ "$1 $2" == 'pr create' ]]; then
        printf 'create:%s\\n' "$GH_TOKEN" >&2
      elif [[ "$1 $2" == 'pr list' ]]; then
        [[ "$GH_TOKEN" == workflow-token ]] || exit 9
      fi
    }
    ${body}
    persist_issue_pr 2952 branch
    printf 'after:%s\\n' "$GH_TOKEN" >&2
  `, 'test', credential], { encoding: 'utf8' });
}

test('PR creation uses trusted credential without changing controller authentication', () => {
  const result = run('trusted-token');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /create:trusted-token/);
  assert.match(result.stderr, /after:workflow-token/);
});

test('PR creation fails closed when the trusted credential is missing', () => {
  const result = run('');
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /PR_REBASE_TOKEN is required for trusted PR creation/);
  assert.doesNotMatch(result.stderr, /create:/);
});
