const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { spawnSync } = require('node:child_process');
const { test } = require('node:test');

const source = readFileSync('.github/scripts/free-model-factory-worker-primitives.sh', 'utf8');

function extract(name) {
  const start = source.indexOf(`${name}() {`);
  assert.notEqual(start, -1, `${name} missing`);
  return source.slice(start, source.indexOf('\n}\n', start) + 3);
}

const helper = extract('factory_push_credential');
const body = extract('persist_issue_pr');

const SECRET_KEYS = [
  'FACTORY_WORKER',
  'FACTORY_WORKER_48_APP_ID',
  'FACTORY_WORKER_48_INSTALLATION_ID',
  'FACTORY_WORKER_48_APP_PRIVATE_KEY',
  'FACTORY_WORKER_APP_MINT_STUB_TOKEN',
  'FACTORY_WORKER_APP_MAPPING',
  'GITHUB_REPOSITORY',
];

function run(credential, extraEnv = {}) {
  const env = { ...process.env, ...extraEnv };
  for (const key of SECRET_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(extraEnv, key)) delete env[key];
  }
  return spawnSync('bash', ['-c', `
    set -Eeuo pipefail
    EXPECTED_HEAD=base DISPLAY=test MODEL=test SOURCE=test WORKER_ID=test WORKER=11
    GH_TOKEN=workflow-token
    export PR_REBASE_TOKEN="$1"
    reject_out_of_scope_diff() { return 0; }
    git() {
      printf 'git:%s\\n' "$*" >&2
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
    ${helper}
    ${body}
    persist_issue_pr 2952 branch
    printf 'after:%s\\n' "$GH_TOKEN" >&2
  `, 'test', credential], { encoding: 'utf8', env });
}

test('PR creation uses trusted credential without changing controller authentication', () => {
  const result = run('trusted-token');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /create:trusted-token/);
  assert.match(result.stderr, /after:workflow-token/);
  assert.doesNotMatch(result.stderr, /x-access-token:/);
});

test('PR creation fails closed when the trusted credential is missing', () => {
  const result = run('');
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /PR_REBASE_TOKEN is required for trusted PR creation/);
  assert.doesNotMatch(result.stderr, /create:/);
});

test('worker 48 without App secrets still uses PR_REBASE_TOKEN', () => {
  const result = run('trusted-token', { FACTORY_WORKER: '48' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /create:trusted-token/);
  assert.doesNotMatch(result.stderr, /x-access-token:/);
});

test('other workers ignore worker 48 App secrets and keep PR_REBASE_TOKEN', () => {
  for (const worker of ['46', '72', '11']) {
    const result = run('trusted-token', {
      FACTORY_WORKER: worker,
      FACTORY_WORKER_48_APP_ID: '123',
      FACTORY_WORKER_48_INSTALLATION_ID: '456',
      FACTORY_WORKER_48_APP_PRIVATE_KEY: 'TEST-ONLY-NOT-A-KEY',
      FACTORY_WORKER_APP_MINT_STUB_TOKEN: 'install-token',
      GITHUB_REPOSITORY: 'JoshCLWren/comic-pile',
    });
    assert.equal(result.status, 0, `${worker} ${result.stderr}`);
    assert.match(result.stderr, /create:trusted-token/);
    assert.doesNotMatch(result.stderr, /x-access-token:install-token/);
  }
});

test('configured worker 48 uses the installation token for push and PR creation', () => {
  const result = run('trusted-token', {
    FACTORY_WORKER: '48',
    FACTORY_WORKER_48_APP_ID: '123',
    FACTORY_WORKER_48_INSTALLATION_ID: '456',
    FACTORY_WORKER_48_APP_PRIVATE_KEY: 'TEST-ONLY-NOT-A-KEY',
    FACTORY_WORKER_APP_MINT_STUB_TOKEN: 'install-token',
    GITHUB_REPOSITORY: 'JoshCLWren/comic-pile',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /git:remote set-url origin https:\/\/x-access-token:install-token@github.com\/JoshCLWren\/comic-pile.git/);
  assert.match(result.stderr, /create:install-token/);
  assert.match(result.stderr, /after:workflow-token/);
});
