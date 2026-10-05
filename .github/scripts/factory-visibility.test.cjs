const assert = require('node:assert/strict');
const test = require('node:test');

const reconcile = require('./factory-visibility.cjs');
const {
  ownerFor,
  reconcileLabels,
  withRetry,
  trusted,
  performedViaUntrustedApp,
  TRUSTED_APP_SLUGS,
} = reconcile._test;

function contextFor(eventName, payload) {
  return {
    eventName,
    payload,
    repo: { owner: 'JoshCLWren', repo: 'comic-pile' },
  };
}

function githubFor({
  labels = [],
  comments = [],
  setLabels,
  updateLabel,
  commentIssueNumbers,
  extraDefinitions = [],
} = {}) {
  const workerDefinitions = Object.fromEntries(
    Array.from({ length: 16 }, (_, index) => [
      `factory:${index + 1}`,
      ['0366D6', `Current next-action owner is ComicPile Factory ${index + 1}`],
    ]),
  );
  const definitions = [
    ...Object.entries({
      factory: ['5319E7', 'Work owned or produced by an autonomous ComicPile factory'],
      ...workerDefinitions,
      'factory:local': ['0366D6', 'Current next-action owner is the local OpenCode factory'],
      'factory:unowned': ['BFDADC', 'Factory work has no current next-action owner'],
      'factory:building': ['FBCA04', 'A factory is actively implementing or repairing this work'],
      'factory:review': ['D4C5F9', 'The exact current head needs review or re-review'],
      'factory:changes-requested': ['D73A4A', 'Actionable review findings currently block progress'],
      'factory:ci': ['1D76DB', 'Review passed and required exact-head checks are being verified'],
      'factory:ready': ['0E8A16', 'All exact-head factory merge gates are satisfied'],
      'factory:blocked': ['B60205', 'A genuine human, credential, or external blocker remains'],
    }).map(([name, [color, description]]) => ({ name, color, description })),
    ...extraDefinitions,
  ];
  const api = {
    listLabelsForRepo() {},
    listLabelsOnIssue() {},
    listComments() {},
    createLabel: async () => {},
    updateLabel: updateLabel || (async () => {}),
    setLabels: setLabels || (async () => {}),
  };
  return {
    paginate: async (operation, params = {}) => {
      if (operation === api.listLabelsForRepo) return definitions;
      if (operation === api.listComments) {
        if (commentIssueNumbers) commentIssueNumbers.push(params.issue_number);
        return comments;
      }
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

test('fixed-model worker tokens map from the roster, not a numeric ceiling', () => {
  assert.equal(ownerFor('opencode-free-model-factory-46'), 'factory:46');
  assert.equal(ownerFor('opencode-free-model-factory-49'), 'factory:49');
  assert.equal(ownerFor('opencode-free-model-factory-73'), 'factory:73');
  assert.equal(ownerFor('opencode-free-model-factory-74'), 'factory:74');
  assert.equal(ownerFor('opencode-free-model-factory-75'), 'factory:75');
  assert.equal(ownerFor('opencode-free-model-factory-76'), 'factory:76');
  assert.equal(ownerFor('opencode-omniroute-factory-73'), 'factory:73');
  assert.equal(ownerFor('opencode-nvidia-factory-11'), 'factory:11');
  // Off-roster / retired ids stay unowned even when historically in 6..71.
  assert.equal(ownerFor('opencode-nvidia-factory-6'), 'factory:unowned');
  assert.equal(ownerFor('opencode-free-model-factory-32'), 'factory:unowned');
  assert.equal(ownerFor('opencode-free-model-factory-71'), 'factory:unowned');
  assert.equal(ownerFor('opencode-free-model-factory-72'), 'factory:unowned');
});

test('head-contributor markers resolve roster workers above the old ceiling', () => {
  const { workerFrom } = reconcile._test;
  const body = '<!-- comic-pile-factory-head-contributor-v1:pr-7:head-' + 'a'.repeat(40) + ':worker-76:epoch-2 -->';
  assert.equal(workerFrom(body), '76');
  assert.equal(ownerFor(workerFrom(body)), 'factory:76');
  assert.equal(ownerFor('worker-73'), 'factory:73');
  assert.equal(ownerFor('72'), 'factory:unowned');
});

test('legacy model-specific label metadata is normalized', async () => {
  const updates = [];
  const github = githubFor({
    extraDefinitions: [{
      name: 'factory:49',
      color: '5319e7',
      description: 'Fixed-model Factory 49: legacy model-specific description',
    }],
    updateLabel: async input => updates.push(input),
  });

  await reconcile({ github, context: contextFor('workflow_dispatch', {}) });

  const update = updates.find(candidate => candidate.name === 'factory:49');
  assert.ok(update);
  assert.equal(update.description, 'Current next-action owner is ComicPile Factory 49');
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

test('fixed-model progress comments use the durable fixed owner', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:building', 'factory:unowned'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('issue_comment', {
      issue: { number: 1089 },
      comment: {
        author_association: 'OWNER',
        user: { login: 'JoshCLWren' },
        body: '<!-- comic-pile-factory-implement-progress-v3:issue-1089:opencode-free-model-factory-49:123 -->',
      },
    }),
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:49'));
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

test('PR refresh preserves a roster fixed-model PR-local owner', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:review', 'factory:49'],
    comments: [{
      author_association: 'OWNER',
      body: '<!-- comic-pile-factory-claim-released-v3:issue-1089:opencode-free-model-factory-49:123 -->',
      created_at: '2026-08-14T14:27:00Z',
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
        body: 'Closes #1089',
        head: {
          ref: 'factory/32-1089-omni',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:49' }],
        number: 1202,
      },
    }),
  });

  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:49'));
  assert.ok(calls[0].labels.includes('factory:review'));
  assert.ok(!calls[0].labels.includes('factory:unowned'));
});

test('released fixed-model PR resolves closing issue instead of worker branch number', async () => {
  const calls = [];
  const commentIssueNumbers = [];
  const github = githubFor({
    labels: ['factory', 'factory:review', 'factory:unowned'],
    comments: [{
      author_association: 'OWNER',
      body: '<!-- comic-pile-factory-claim-released-v3:issue-1089:opencode-free-model-factory-49:123 -->',
      created_at: '2026-08-14T14:27:00Z',
      user: { login: 'JoshCLWren' },
    }],
    commentIssueNumbers,
    setLabels: async input => calls.push(input),
  });

  await reconcile({
    github,
    context: contextFor('pull_request_target', {
      action: 'synchronize',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        body: 'Closes #1089',
        head: {
          ref: 'factory/32-1089-omni',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:unowned' }],
        number: 1202,
      },
    }),
  });

  assert.deepEqual(commentIssueNumbers, [1089]);
  assert.equal(calls.length, 1);
  const owners = calls[0].labels.filter(label => (
    label === 'factory:unowned'
    || label === 'factory:local'
    || /^factory:(?:[1-9]|[1-3][0-9]|[4-7][0-9])$/.test(label)
  ));
  assert.deepEqual(owners, ['factory:unowned']);
  assert.ok(calls[0].labels.includes('factory:review'));
});

test('PR refresh preserves one external owner after the linked issue is released', async () => {
  const calls = [];
  const github = githubFor({
    labels: [
      'bug',
      'factory',
      'factory:13',
      'factory:unowned',
      'factory:review',
    ],
    comments: [{
      author_association: 'OWNER',
      body: '<!-- comic-pile-factory-claim-released-v3:issue-1149:chatgpt-factory-2:123 -->',
      created_at: '2026-08-13T06:00:00Z',
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
        body: 'Closes #1149',
        head: {
          ref: 'factory/1149-omniroute',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [
          { name: 'factory' },
          { name: 'factory:13' },
          { name: 'factory:unowned' },
        ],
        number: 1155,
      },
    }),
  });

  assert.equal(calls.length, 1);
  const owners = calls[0].labels.filter(label => (
    label === 'factory:unowned'
    || label === 'factory:local'
    || /^factory:(?:[1-9]|[1-3][0-9]|[4-7][0-9])$/.test(label)
  ));
  assert.deepEqual(owners, ['factory:13']);
  assert.ok(calls[0].labels.includes('factory:review'));
});

test('native APPROVED review from OWNER makes no label API calls', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:ci', 'factory:43'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        head: {
          ref: 'factory/43-1386-opencode-free',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:43' }, { name: 'factory:ci' }],
        number: 1390,
      },
      review: {
        state: 'APPROVED',
        author_association: 'OWNER',
        user: { login: 'JoshCLWren' },
      },
    }),
  });
  assert.equal(calls.length, 0);
});

test('native APPROVED review from MEMBER makes no label API calls', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:ready', 'factory:43'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        head: {
          ref: 'factory/43-1386-opencode-free',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:43' }, { name: 'factory:ready' }],
        number: 1390,
      },
      review: {
        state: 'APPROVED',
        author_association: 'MEMBER',
        user: { login: 'some-member' },
      },
    }),
  });
  assert.equal(calls.length, 0);
});

test('native APPROVED review from COLLABORATOR makes no label API calls', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:review', 'factory:43'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        head: {
          ref: 'factory/43-1386-opencode-free',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:43' }, { name: 'factory:review' }],
        number: 1390,
      },
      review: {
        state: 'APPROVED',
        author_association: 'COLLABORATOR',
        user: { login: 'some-collaborator' },
      },
    }),
  });
  assert.equal(calls.length, 0);
});

test('native APPROVED review from github-actions[bot] makes no label API calls', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:ci', 'factory:43'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        head: {
          ref: 'factory/43-1386-opencode-free',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:43' }, { name: 'factory:ci' }],
        number: 1390,
      },
      review: {
        state: 'APPROVED',
        author_association: 'OWNER',
        user: { login: 'github-actions[bot]' },
      },
    }),
  });
  assert.equal(calls.length, 0);
});

test('native APPROVED review from worker App with OWNER association makes no label API calls', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:ready', 'factory:48'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        head: {
          ref: 'factory/48-3136-opencode-free',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:48' }, { name: 'factory:ready' }],
        number: 3136,
      },
      review: {
        state: 'APPROVED',
        author_association: 'OWNER',
        user: { login: 'MarkCordova[bot]' },
        performed_via_github_app: { slug: 'mark-cordova-comic-pile', owner: { login: 'JoshCLWren' } },
      },
    }),
  });
  assert.equal(calls.length, 0);
});

test('CHANGES_REQUESTED review still sets factory:changes-requested', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:review', 'factory:43'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        head: {
          ref: 'factory/43-1386-opencode-free',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:43' }, { name: 'factory:review' }],
        number: 1390,
      },
      review: {
        state: 'CHANGES_REQUESTED',
        author_association: 'OWNER',
        user: { login: 'JoshCLWren' },
      },
    }),
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:changes-requested'));
  assert.ok(!calls[0].labels.includes('factory:review'));
  assert.ok(!calls[0].labels.includes('factory:ci'));
});

test('dismissed review resets to factory:review', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:changes-requested', 'factory:43'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'dismissed',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        head: {
          ref: 'factory/43-1386-opencode-free',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:43' }, { name: 'factory:changes-requested' }],
        number: 1390,
      },
      review: {
        state: 'CHANGES_REQUESTED',
        author_association: 'OWNER',
        user: { login: 'JoshCLWren' },
      },
    }),
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:review'));
  assert.ok(!calls[0].labels.includes('factory:changes-requested'));
  assert.ok(!calls[0].labels.includes('factory:ci'));
});

test('worker GitHub App with OWNER association is NOT trusted for marker reconcile', () => {
  const workerAppComment = {
    author_association: 'OWNER',
    user: { login: 'mark-cordova[bot]' },
    body: '<!-- comic-pile-factory-implement-claim-v3:issue-123:mark-cordova:456 -->',
    performed_via_github_app: { slug: 'mark-cordova' },
  };
  assert.equal(trusted(workerAppComment), false);
  assert.equal(performedViaUntrustedApp(workerAppComment), true);
});

test('github-actions[bot] with NONE association IS trusted for marker reconcile', () => {
  const actionsComment = {
    author_association: 'NONE',
    user: { login: 'github-actions[bot]' },
    body: '<!-- comic-pile-factory-implement-claim-v3:issue-123:local:456 -->',
    performed_via_github_app: { slug: 'github-actions' },
  };
  assert.equal(trusted(actionsComment), true);
  assert.equal(performedViaUntrustedApp(actionsComment), false);
});

test('github-actions App slug with a non-actions login and NONE association is NOT trusted', () => {
  // Mirrors Python trusted_comment_bodies: require exact github-actions[bot] login
  // when association is not OWNER/MEMBER/COLLABORATOR. Slug alone is not enough.
  const spoof = {
    author_association: 'NONE',
    user: { login: 'not-actions[bot]' },
    body: '<!-- comic-pile-factory-implement-claim-v3:issue-123:local:456 -->',
    performed_via_github_app: { slug: 'github-actions' },
  };
  assert.equal(trusted(spoof), false);
  assert.equal(performedViaUntrustedApp(spoof), false);
});

test('github-actions[bot] with NONE and no performed_via_github_app IS trusted', () => {
  const actionsComment = {
    author_association: 'NONE',
    user: { login: 'github-actions[bot]' },
    body: '<!-- comic-pile-factory-implement-claim-v3:issue-123:local:456 -->',
  };
  assert.equal(trusted(actionsComment), true);
});

test('human OWNER comment with no App IS trusted', () => {
  const humanComment = {
    author_association: 'OWNER',
    user: { login: 'JoshCLWren' },
    body: '<!-- comic-pile-factory-implement-claim-v3:issue-123:local:456 -->',
  };
  assert.equal(trusted(humanComment), true);
  assert.equal(performedViaUntrustedApp(humanComment), false);
});

test('TRUSTED_APP_SLUGS is exactly github-actions', () => {
  assert.deepEqual([...TRUSTED_APP_SLUGS].sort(), ['github-actions']);
});

test('issue_comment reconcile rejects worker App comment even with OWNER association', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:building', 'factory:unowned'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('issue_comment', {
      issue: { number: 44, pull_request: { url: 'https://api.github.test/pulls/44' } },
      comment: {
        author_association: 'OWNER',
        user: { login: 'mark-cordova[bot]' },
        body: '<!-- comic-pile-factory-implement-progress-v3:issue-44:mark-cordova:123 -->',
        performed_via_github_app: { slug: 'mark-cordova' },
      },
    }),
  });
  // Worker App comment should be rejected, no label changes
  assert.equal(calls.length, 0);
});

test('pull_request_review reconcile rejects worker App review even with OWNER association', async () => {
  const calls = [];
  const github = githubFor({
    labels: ['factory', 'factory:review', 'factory:local'],
    setLabels: async input => calls.push(input),
  });
  await reconcile({
    github,
    context: contextFor('pull_request_review', {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        number: 100,
        head: {
          ref: 'factory/999-local',
          repo: { full_name: 'JoshCLWren/comic-pile' },
        },
        labels: [{ name: 'factory' }, { name: 'factory:review' }, { name: 'factory:local' }],
      },
      review: {
        author_association: 'OWNER',
        user: { login: 'mark-cordova[bot]' },
        state: 'APPROVED',
        performed_via_github_app: { slug: 'mark-cordova' },
      },
    }),
  });
  // Worker App review should be rejected, no label changes
  assert.equal(calls.length, 0);
});

test('pull_request_review trust: github-actions[bot] is trusted, worker App is not', () => {
  // Order-independent with #3157: native APPROVED must not assert stage/label
  // promotion here. #3157 makes APPROVED a label no-op; this contract only
  // checks who may author a trusted review signal.
  const actionsReview = {
    author_association: 'NONE',
    user: { login: 'github-actions[bot]' },
    state: 'APPROVED',
    performed_via_github_app: { slug: 'github-actions' },
  };
  const workerReview = {
    author_association: 'OWNER',
    user: { login: 'mark-cordova[bot]' },
    state: 'APPROVED',
    performed_via_github_app: { slug: 'mark-cordova' },
  };
  assert.equal(trusted(actionsReview), true);
  assert.equal(performedViaUntrustedApp(actionsReview), false);
  assert.equal(trusted(workerReview), false);
  assert.equal(performedViaUntrustedApp(workerReview), true);
});
