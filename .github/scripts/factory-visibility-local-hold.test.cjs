const assert = require('node:assert/strict');
const test = require('node:test');

const reconcile = require('./factory-visibility.cjs');

function contextFor(eventName, payload) {
  return { eventName, payload, repo: { owner: 'JoshCLWren', repo: 'comic-pile' } };
}

function githubFor({ labels, setLabels }) {
  const names = [
    'factory', 'factory:local', 'factory:unowned', 'factory:80', 'factory:building',
    'factory:review', 'factory:changes-requested', 'factory:ci', 'factory:ready', 'factory:blocked',
  ];
  const api = {
    listLabelsForRepo: async () => ({ data: names.map(name => ({ name, color: '0366D6', description: '' })), headers: {}, status: 200 }),
    listLabelsOnIssue: async () => ({ data: labels.map(name => ({ name })), headers: {}, status: 200 }),
    listComments: async () => ({ data: [], headers: {}, status: 200 }),
    setLabels: async input => { await setLabels(input); return { data: [], headers: {}, status: 200 }; },
    createLabel: async () => ({ data: {}, headers: {}, status: 201 }),
    updateLabel: async () => ({ data: {}, headers: {}, status: 200 }),
  };
  return {
    rest: { issues: api, pulls: {} },
    paginate: async (_method, params) => (await api.listLabelsForRepo(params)).data,
  };
}

const trustedBot = { author_association: 'CONTRIBUTOR', user: { login: 'github-actions[bot]' } };

for (const [name, body] of [
  ['controller claim', '<!-- comic-pile-factory-controller-claim-v1:issue-3609:80:1792495979 -->'],
  ['worker progress', '<!-- comic-pile-factory-implement-progress-v3:issue-3609:opencode-free-model-factory-80:1792495979 -->'],
  ['claim release', '<!-- comic-pile-factory-claim-released-v3:issue-3609:opencode-free-model-factory-80:1792495979:repairs-pushed-handoff -->'],
]) {
  test(`factory:local hold survives a trusted ${name} marker`, async () => {
    const calls = [];
    const github = githubFor({
      labels: ['bug', 'factory', 'factory:local'],
      setLabels: async input => calls.push(input),
    });
    await reconcile({
      github,
      context: contextFor('issue_comment', {
        issue: { number: 3609 },
        comment: { ...trustedBot, body },
      }),
    });
    for (const call of calls) {
      assert.ok(call.labels.includes('factory:local'), JSON.stringify(call.labels));
      assert.ok(!call.labels.includes('factory:unowned'));
      assert.ok(!call.labels.includes('factory:80'));
    }
  });
}
