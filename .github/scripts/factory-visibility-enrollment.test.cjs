const assert = require('node:assert/strict');
const test = require('node:test');
const { reconcileMissingPrLabels } = require('./factory-visibility.cjs');

const sha = 'a'.repeat(40);
const pr = (number = 1) => ({
  number, state: 'open', draft: false, user: { login: 'JoshCLWren' },
  head: { sha, repo: { full_name: 'JoshCLWren/comic-pile' } },
});

async function run({ prs = [pr()], labels = [], comments = [], event = 'schedule' } = {}) {
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
    payload: { pull_request: prs[0] },
  } });
  return { writes, reads };
}

test('open event enrolls a manual PR and preserves unrelated labels atomically', async () => {
  const { writes } = await run({ labels: ['bug'], event: 'pull_request_target' });
  assert.equal(writes.length, 1);
  assert.deepEqual(new Set(writes[0].labels),
    new Set(['bug', 'factory', 'factory:review', 'factory:unowned']));
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

test('forks, dependency bots, drafts, and closed PRs are excluded', async () => {
  const fork = pr();
  fork.head.repo.full_name = 'someone/comic-pile';
  const { writes } = await run({ prs: [fork, { ...pr(), draft: true },
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
