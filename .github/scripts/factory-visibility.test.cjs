const assert = require('node:assert/strict');
const test = require('node:test');

const reconcile = require('./factory-visibility.cjs');
const { ownerFor, reconcileLabels, withRetry } = reconcile._test;

function contextFor(eventName, payload) {
  return {
    eventName,
    payload,
    repo: { owner: 'JoshCLWren', repo: 'comic-pile' },
  };
}

function githubFor({ labels = [], comments = [], setLabels } = {}) {
  const definitions = Object.entries({
    factory: ['5319E7', 'Work owned or produced by an autonomous ComicPile factory'],
    'factory:1': ['0366D6', 'Current next-action owner is ComicPile Factory 1'],
    'factory:2': ['0366D6', 'Current next-action owner is ComicPile Factory 2'],
    'factory:3': ['0366D6', 'Current next-action owner is ComicPile Factory 3'],
    'factory:4': ['0366D6', 'Current next-action owner is ComicPile Factory 4'],
    'factory:5': ['0366D6', 'Current next-action owner is ComicPile Factory 5'],
    'factory:local': ['0366D6', 'Current next-action owner is the local OpenCode factory'],
    'factory:unowned': ['BFDADC', 'Factory work has no current next-action owner'],
    'factory:building': ['FBCA04', 'A factory is actively implementing or repairing this work'],
    'factory:review': ['D4C5F9', 'The exact current head needs review or re-review'],
    'factory:changes-requested': ['D73A4A', 'Actionable review findings currently block progress'],
    'factory:ci': ['1D76DB', 'Review passed and required exact-head checks are being verified'],
    'factory:ready': ['0E8A16', 'All exact-head factory merge gates are satisfied'],
    'factory:blocked': ['B60205', 'A genuine human, credential, or external blocker remains'],
  }).map(([name, [color, description]]) => ({ name, color, description }));
  const api = {
    listLabelsForRepo() {},
    listLabelsOnIssue() {},
    listComments() {},
    createLabel: async () => {},
    updateLabel: async () => {},
    setLabels: setLabels || (async () => {}),
  };
  return {
    paginate: async operation => {
      if (operation === api.listLabelsForRepo) return definitions;
      if (operation === api.listComments) return comments;
      return labels.map(name => ({ name }));
    },
    rest: { issues: api },
  };
}

test('canonical local worker tokens map to the local owner', () => {
  assert.equal(ownerFor('local'), 'factory:local');
  assert.equal(ownerFor('local-opencode'), 'factory:local');
  assert.equal(ownerFor('local-opencode-debian'), 'factory:local');
});

test('label reconciliation replaces both groups with one atomic call', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['bug', 'factory', 'factory:building', 'factory:unowned'],
    setLabels: async input => calls.push(input),
  });
  await reconcileLabels(github, contextFor('workflow_dispatch', {}), 12, {
    owner: 'factory:local',
    stage: 'factory:review',
  });
  assert.equal(calls.length, 1);
  assert.deepEqual(
    new Set(calls[0].labels),
    new Set(['bug', 'factory', 'factory:local', 'factory:review']),
  );
});

test('transient GitHub failures are retried', async () => {
  let attempts = 0;
  const result = await withRetry(async () => {
    attempts += 1;
    if (attempts === 1) throw Object.assign(new Error('temporary failure'), { status: 502 });
    return 'ok';
  }, { delay: 0 });
  assert.equal(result, 'ok');
  assert.equal(attempts, 2);
});

test('PR progress comments preserve an advanced review stage and local owner', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:review', 'factory:unowned'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('issue_comment', {
      issue: { number: 44, pull_request: { url: 'https://api.github.test/pulls/44' } },
      comment: {
        author_association: 'OWNER',
        user: { login: 'JoshCLWren' },
        body: '<!-- comic-pile-factory-fix-progress-v3:abc:local:123 -->',
      },
    }),
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:local'));
  assert.ok(calls[0].labels.includes('factory:review'));
  assert.ok(!calls[0].labels.includes('factory:building'));
  assert.ok(!calls[0].labels.includes('factory:unowned'));
});

test('PR synchronize events refresh owner and stage from the linked issue', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:building', 'factory:5'],
    comments: [{
      author_association: 'OWNER',
      body: '<!-- comic-pile-factory-implement-claim-v3:issue-999:local:123:attempt-1 -->',
      created_at: '2026-08-09T12:00:00Z',
      user: { login: 'JoshCLWren' },
    }],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_target', {
      action: 'synchronize',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        body: 'Closes #999',
        head: {
          ref: 'factory/999-atomic-label-reconciliation',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }],
        number: 1000,
      },
    }),
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:local'));
  assert.ok(calls[0].labels.includes('factory:review'));
  assert.ok(!calls[0].labels.includes('factory:5'));
  assert.ok(!calls[0].labels.includes('factory:building'));
});
