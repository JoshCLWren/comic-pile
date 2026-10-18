const assert = require('node:assert/strict');
const test = require('node:test');
const { reconcileMissingPrLabels } = require('./factory-visibility.cjs');

const sha = 'a'.repeat(40);
const pr = (number = 1) => ({
  number, state: 'open', draft: false, user: { login: 'JoshCLWren' },
  head: { sha, repo: { full_name: 'JoshCLWren/comic-pile' } },
});

async function run({ prs = [pr()], labels = [], comments = [], event = 'schedule', action = 'opened' } = {}) {
  const writes = [];
  const reads = [];
  const issues = {
    listLabelsOnIssue() {}, listComments() {},
    async setLabels(input) { writes.push(input); },
  };
  const pulls = { list() {} };
  const github = {
    rest: { issues, pulls },
    async paginate(operation, params) {
      reads.push(params);
      if (operation === pulls.list) return prs;
      if (operation === issues.listComments) return comments;
      return labels.map(name => ({ name }));
    },
  };
  await reconcileMissingPrLabels({ github, context: {
    eventName: event, repo: { owner: 'JoshCLWren', repo: 'comic-pile' },
    payload: { pull_request: prs[0], action },
  } });
  return { writes, reads };
}

test('open event enrolls a manual PR and preserves unrelated labels atomically', async () => {
  const { writes } = await run({ labels: ['bug'], event: 'pull_request_target' });
  assert.equal(writes.length, 1);
  assert.deepEqual(new Set(writes[0].labels),
    new Set(['bug', 'factory', 'factory:review', 'factory:unowned']));
});

test('local factory lease is preserved while its missing review stage is enrolled', async () => {
  const { writes } = await run({ labels: ['factory:local', 'bug'] });
  assert.equal(writes.length, 1);
  assert.deepEqual(new Set(writes[0].labels),
    new Set(['bug', 'factory', 'factory:review', 'factory:local']));
});

test('complete local lease stays untouched until local session releases it', async () => {
  const { writes } = await run({ labels: ['factory', 'factory:local', 'factory:review'] });
  assert.deepEqual(writes, []);
});

test('mentioning a manual-only marker in documentation does not opt out a PR', async () => {
  const inline = { ...pr(), body: 'To opt out, use `<!-- factory-execution:manual-only -->`.' };
  const documented = { ...pr(), body: 'Example:\n```markdown\n<!-- factory-execution:manual-only -->\n```' };
  for (const item of [inline, documented]) {
    const { writes } = await run({ prs: [item] });
    assert.equal(writes.length, 1);
    assert.ok(writes[0].labels.includes('factory:review'));
  }
});

test('a standalone manual-only directive opts out even with factory labels', async () => {
  const explicit = { ...pr(), body: 'Operator-only work.\n<!-- factory-execution:manual-only -->\n' };
  const { writes } = await run({ prs: [explicit], labels: ['factory'] });
  assert.deepEqual(writes, []);
});
test('scheduled sweep paginates all open PRs', async () => {
  const { writes, reads } = await run({ prs: [pr(1), pr(2)] });
  assert.deepEqual(writes.map(input => input.issue_number), [1, 2]);
  assert.equal(reads[0].state, 'open');
  assert.equal(reads[0].per_page, 100);
});

test('missing factory label preserves current owner and advanced stage', async () => {
  const { writes } = await run({ labels: ['factory:59', 'factory:ready', 'bug'] });
  assert.deepEqual(new Set(writes[0].labels),
    new Set(['bug', 'factory', 'factory:59', 'factory:ready']));
});

test('complete metadata is left untouched', async () => {
  const { writes } = await run({ labels: ['factory', 'factory:ci', 'factory:unowned'] });
  assert.deepEqual(writes, []);
});

test('dependency bots, deleted heads, drafts, and closed PRs are excluded', async () => {
  const { writes } = await run({ prs: [{ ...pr(), head: { sha, repo: null } }, { ...pr(), draft: true },
    { ...pr(), state: 'closed' }, { ...pr(), user: { login: 'dependabot[bot]' } },
    { ...pr(), user: { login: 'renovate[bot]' } }] });
  assert.deepEqual(writes, []);
});

test('only trusted current-head review verdicts recover a missing stage', async () => {
  const comment = (head, verdict, association, day) => ({
    body: `<!-- comic-pile-factory-review-v2:${head}:${verdict} -->`,
    author_association: association, created_at: `2026-09-${day}T00:00:00Z`,
  });
  const { writes } = await run({ comments: [
    comment(sha, 'pass', 'OWNER', 20),
    comment('b'.repeat(40), 'changes-required', 'OWNER', 21),
    comment(sha, 'changes-required', 'NONE', 22),
  ] });
  assert.ok(writes[0].labels.includes('factory:ci'));
});

test('current-head changes-required verdict requests repair', async () => {
  const { writes } = await run({ comments: [{
    body: `<!-- comic-pile-factory-review-v2:${sha}:changes-required -->`,
    author_association: 'OWNER', created_at: '2026-09-20T00:00:00Z',
  }] });
  assert.ok(writes[0].labels.includes('factory:changes-requested'));
});

for (const event of ['schedule', 'pull_request_target']) {
  test(`${event} enrolls a first-time fork with the normal review gates`, async () => {
    const fork = { ...pr(), body: 'Closes #3893', user: { login: 'first-timer' },
      head: { sha, ref: 'fix/issue-3893', repo: { full_name: 'first-timer/comic-pile' } } };
    const { writes } = await run({ prs: [fork], event, labels: ['bug'] });
    assert.deepEqual(new Set(writes[0].labels),
      new Set(['bug', 'factory', 'factory:review', 'factory:unowned']));
  });
}

for (const previous of ['factory:ci', 'factory:ready']) {
  test(`a contributor push invalidates ${previous} while preserving ownership`, async () => {
    const fork = { ...pr(), head: { sha, repo: { full_name: 'contributor/comic-pile' } } };
    const { writes } = await run({ prs: [fork], event: 'pull_request_target', action: 'synchronize',
      labels: ['factory', previous, 'factory:local', 'bug'] });
    assert.deepEqual(new Set(writes[0].labels),
      new Set(['bug', 'factory', 'factory:review', 'factory:local']));
  });
}
