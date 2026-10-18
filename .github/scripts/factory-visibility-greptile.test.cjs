const assert = require('node:assert/strict');
const test = require('node:test');

const reconcile = require('./factory-visibility.cjs');
const {
  trusted,
  isRepairRoutingReviewer,
  unresolvedReviewerBotThreads,
  REPAIR_ROUTING_REVIEWER_BOTS,
  TRUSTED_APP_SLUGS,
} = reconcile._test;

const HEAD = 'a'.repeat(40);
const OLD_HEAD = 'b'.repeat(40);

function thread({ login = 'greptile-apps', isResolved = false, isOutdated = false } = {}) {
  return { isResolved, isOutdated, comments: { nodes: [{ author: { login } }] } };
}

function githubFor({
  labels = ['factory', 'factory:review', 'factory:unowned'],
  threads = [],
  threadPages,
  liveHead = HEAD,
  setLabels,
  graphqlCalls,
  pullCalls,
} = {}) {
  const pages = threadPages || [{ nodes: threads }];
  const api = {
    listLabelsForRepo() {},
    listLabelsOnIssue() {},
    listComments() {},
    createLabel: async () => {},
    updateLabel: async () => {},
    setLabels: setLabels || (async () => {}),
  };
  return {
    paginate: async (operation) => {
      if (operation === api.listLabelsForRepo) return [];
      if (operation === api.listComments) return [];
      return labels.map(name => ({ name }));
    },
    graphql: async (query, variables) => {
      if (graphqlCalls) graphqlCalls.push({ query, variables });
      const index = variables.after ? Number(variables.after.slice('cursor-'.length)) : 0;
      const page = pages[index];
      const hasNextPage = index + 1 < pages.length || page.hasNextPage === true;
      const pageInfo = 'pageInfo' in page
        ? page.pageInfo
        : { hasNextPage, endCursor: hasNextPage ? `cursor-${index + 1}` : null };
      return {
        repository: {
          pullRequest: {
            reviewThreads: { nodes: page.nodes, ...(pageInfo === undefined ? {} : { pageInfo }) },
          },
        },
      };
    },
    rest: {
      issues: api,
      pulls: {
        get: async (params) => {
          if (pullCalls) pullCalls.push(params);
          return { data: { head: { sha: liveHead } } };
        },
      },
    },
  };
}

function greptileReview(overrides = {}) {
  return {
    id: 1,
    author_association: 'NONE',
    user: { login: 'greptile-apps[bot]', type: 'Bot' },
    state: 'COMMENTED',
    commit_id: HEAD,
    body: '',
    ...overrides,
  };
}

function reviewContext(review, { headSha = HEAD } = {}) {
  return {
    eventName: 'pull_request_review',
    repo: { owner: 'JoshCLWren', repo: 'comic-pile' },
    payload: {
      action: 'submitted',
      repository: { full_name: 'JoshCLWren/comic-pile' },
      pull_request: {
        number: 100,
        head: { ref: 'factory/49-3154-greptile', sha: headSha, repo: { full_name: 'JoshCLWren/comic-pile' } },
        labels: [{ name: 'factory' }, { name: 'factory:review' }, { name: 'factory:unowned' }],
      },
      review,
    },
  };
}

async function run(review, options = {}) {
  const calls = [];
  const graphqlCalls = [];
  const pullCalls = [];
  const github = githubFor({ ...options, setLabels: async input => calls.push(input), graphqlCalls, pullCalls });
  await reconcile({ github, context: reviewContext(review, options) });
  return { calls, graphqlCalls, pullCalls };
}

test('reviewer-bot allowlist is separate from marker trust', () => {
  assert.deepEqual([...REPAIR_ROUTING_REVIEWER_BOTS], ['greptile-apps[bot]']);
  assert.equal(isRepairRoutingReviewer(greptileReview()), true);
  // Greptile is a routing signal only; it must never become a trusted marker author.
  assert.equal(trusted(greptileReview()), false);
  assert.equal(trusted({ ...greptileReview(), body: '<!-- comic-pile-factory-ready-v1:x -->' }), false);
  assert.equal(TRUSTED_APP_SLUGS.has('greptile-apps'), false);
  assert.equal(isRepairRoutingReviewer({ user: { login: 'greptile-apps' } }), false);
  assert.equal(isRepairRoutingReviewer({ user: { login: 'coderabbitai[bot]' } }), false);
});

test('Greptile COMMENTED review with unresolved current-head findings routes to changes-requested', async () => {
  const { calls, graphqlCalls } = await run(greptileReview(), { threads: [thread()] });
  assert.equal(graphqlCalls.length, 1);
  assert.equal(graphqlCalls[0].variables.number, 100);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].issue_number, 100);
  assert.ok(calls[0].labels.includes('factory:changes-requested'));
  assert.ok(!calls[0].labels.includes('factory:review'));
  assert.ok(calls[0].labels.includes('factory:unowned'));
});

test('Greptile REST login suffix is also matched in GraphQL thread authors', async () => {
  const { calls } = await run(greptileReview(), { threads: [thread({ login: 'greptile-apps[bot]' })] });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:changes-requested'));
});

test('Greptile findings beyond the first thread page still route', async () => {
  const { calls, graphqlCalls } = await run(greptileReview(), {
    threadPages: [
      { nodes: Array.from({ length: 100 }, () => thread({ isResolved: true })) },
      { nodes: [thread()] },
    ],
  });
  assert.equal(graphqlCalls.length, 2);
  assert.equal(graphqlCalls[0].variables.after, null);
  assert.equal(graphqlCalls[1].variables.after, 'cursor-1');
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:changes-requested'));
});

test('truncated thread pagination with no findings seen fails closed instead of skipping', async () => {
  for (const truncated of [
    { nodes: [thread({ isResolved: true })], pageInfo: { hasNextPage: true, endCursor: null } },
    { nodes: [thread({ isResolved: true })], pageInfo: undefined },
    { nodes: null, pageInfo: { hasNextPage: false, endCursor: null } },
  ]) {
    const calls = [];
    const github = githubFor({ threadPages: [truncated], setLabels: async input => calls.push(input) });
    await assert.rejects(
      reconcile({ github, context: reviewContext(greptileReview()) }),
      /review-thread pagination was incomplete/,
    );
    assert.equal(calls.length, 0);
  }
});

test('truncated thread pagination still routes when an open Greptile finding was already seen', async () => {
  const { calls } = await run(greptileReview(), {
    threadPages: [{ nodes: [thread()], pageInfo: { hasNextPage: true, endCursor: null } }],
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:changes-requested'));
});

test('thread counting reports incomplete when the page limit is exhausted', async () => {
  const github = githubFor({
    threadPages: [{ nodes: [thread({ isResolved: true })] }, { nodes: [thread()] }],
  });
  const context = reviewContext(greptileReview());
  assert.deepEqual(
    await unresolvedReviewerBotThreads(github, context, 100, { pageLimit: 1 }),
    { count: 0, complete: false },
  );
  assert.deepEqual(
    await unresolvedReviewerBotThreads(github, context, 100),
    { count: 1, complete: true },
  );
});

test('Greptile review routes only when it still targets the live PR head', async () => {
  // The globally serialized reconciler can run after a newer push; the event
  // payload head then still equals the review commit, but the live head moved.
  const { calls, graphqlCalls, pullCalls } = await run(greptileReview(), {
    threads: [thread()],
    liveHead: OLD_HEAD,
  });
  assert.equal(pullCalls.length, 1);
  assert.equal(pullCalls[0].pull_number, 100);
  assert.equal(calls.length, 0);
  assert.equal(graphqlCalls.length, 0);
});

test('Greptile review on an older head does not route', async () => {
  const { calls, graphqlCalls } = await run(greptileReview({ commit_id: OLD_HEAD }), { threads: [thread()] });
  assert.equal(calls.length, 0);
  assert.equal(graphqlCalls.length, 0);
});

test('Greptile review with only resolved, outdated, or other-author threads does not route', async () => {
  const { calls } = await run(greptileReview(), {
    threads: [
      thread({ isResolved: true }),
      thread({ isOutdated: true }),
      thread({ login: 'some-human' }),
      thread({ login: 'pr-agent[bot]' }),
    ],
  });
  assert.equal(calls.length, 0);
});

test('Greptile review with no inline findings does not route', async () => {
  const { calls } = await run(greptileReview(), { threads: [] });
  assert.equal(calls.length, 0);
});

test('Greptile APPROVED never mutates labels', async () => {
  const { calls, graphqlCalls } = await run(greptileReview({ state: 'APPROVED' }), { threads: [thread()] });
  assert.equal(calls.length, 0);
  assert.equal(graphqlCalls.length, 0);
});

test('a non-allowlisted bot COMMENTED review with open threads still does not route', async () => {
  const { calls, graphqlCalls } = await run(
    greptileReview({ user: { login: 'other-reviewer[bot]' } }),
    { threads: [thread({ login: 'other-reviewer' })] },
  );
  assert.equal(calls.length, 0);
  assert.equal(graphqlCalls.length, 0);
});

test('trusted CHANGES_REQUESTED routing is unchanged and does not query threads', async () => {
  const { calls, graphqlCalls } = await run({
    author_association: 'NONE',
    user: { login: 'github-actions[bot]' },
    state: 'CHANGES_REQUESTED',
    performed_via_github_app: { slug: 'github-actions' },
  });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].labels.includes('factory:changes-requested'));
  assert.equal(graphqlCalls.length, 0);
});

test('reconciler workflow fires on submitted pull_request_review events', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const workflow = fs.readFileSync(
    path.join(__dirname, '..', 'workflows', 'factory-issue-pr-state-reconciler.yml'),
    'utf8',
  );
  assert.match(workflow, /pull_request_review:\s*\n\s*types:\s*\[submitted, dismissed\]/);
});
