
const assert = require('assert');
const {
  parseFactoryComment,
  trusted,
} = require('./factory-visibility.cjs')._test;

const TRUSTED_COMMENT = {
  author_association: 'OWNER',
  user: { login: 'JoshCLWren' },
  performed_via_github_app: null,
};

const UNTRUSTED_COMMENT = {
  author_association: 'NONE',
  user: { login: 'attacker' },
  performed_via_github_app: null,
};

const TEST_CASES = [
  {
    name: 'Valid marker changes stage',
    body: '<!-- comic-pile-factory-ready-v1:pr-123 -->',
    trusted: true,
    expectedStage: 'factory:ready',
  },
  {
    name: 'Marker in prose is rejected',
    body: 'Check this out: <!-- comic-pile-factory-ready-v1:pr-123 -->',
    trusted: true,
    expectedStage: null,
  },
  {
    name: 'Fenced marker is rejected',
    body: '```\n<!-- comic-pile-factory-ready-v1:pr-123 -->\n```',
    trusted: true,
    expectedStage: null,
  },
  {
    name: 'Partial marker is rejected',
    body: '<!-- comic-pile-factory-ready-v1: -->',
    trusted: true,
    expectedStage: null,
  },
  {
    name: 'Malformed marker is rejected',
    body: '<!-- comic-pile-factory-ready-v1:pr-123:extra -->',
    trusted: true,
    expectedStage: null,
  },
  {
    name: 'Marker on second line is rejected',
    body: 'First line\n<!-- comic-pile-factory-ready-v1:pr-123 -->',
    trusted: true,
    expectedStage: null,
  },
  {
    name: 'Legacy verdict PASS moves to CI',
    body: '<!-- comic-pile-factory-review-v1:sha123:pass -->',
    trusted: true,
    expectedStage: 'factory:ci',
  },
  {
    name: 'Legacy verdict CHANGES-REQUIRED moves to changes-requested',
    body: '<!-- comic-pile-factory-review-v1:sha123:changes-required -->',
    trusted: true,
    expectedStage: 'factory:changes-requested',
  },
  {
    name: 'Untrusted actor is rejected by trusted()',
    body: '<!-- comic-pile-factory-ready-v1:pr-123 -->',
    trusted: false,
    expectedStage: 'factory:ready', // parseFactoryComment doesn't check trust
  },
];

console.log('Running parseFactoryComment tests...');
TEST_CASES.forEach((tc) => {
  const result = parseFactoryComment(tc.body);
  const stage = result ? result.stage : null;
  try {
    assert.strictEqual(stage, tc.expectedStage, `Failed: ${tc.name}`);
    console.log(`✅ ${tc.name}`);
  } catch (e) {
    console.error(`❌ ${tc.name} - Expected ${tc.expectedStage}, got ${stage}`);
    process.exit(1);
  }
});

console.log('\nRunning trusted() tests...');
assert.strictEqual(trusted(TRUSTED_COMMENT), true, 'Owner should be trusted');
assert.strictEqual(trusted(UNTRUSTED_COMMENT), false, 'External should not be trusted');
console.log('✅ trusted() tests passed');
