import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  classifyV2Path,
  evaluateOperations,
  loadBaseline,
  loadFragmentOperations,
  loadInventoryOperations,
  mergeOperations,
  renderBaseline,
} from './check_v2_aip_shapes.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const cliPath = path.join(repoRoot, 'scripts', 'check_v2_aip_shapes.mjs');
const baselinePath = path.join(repoRoot, 'docs/api/v2-aip-shapes-baseline.json');

function writeFixture(files) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'v2-aip-shapes-'));
  for (const [name, body] of Object.entries(files)) {
    const target = path.join(root, name);
    mkdirSync(path.dirname(target), {recursive: true});
    writeFileSync(target, body, 'utf8');
  }
  return root;
}

function removeFixture(root) {
  rmSync(root, {recursive: true, force: true});
}

function runCli(args) {
  try {
    const stdout = execFileSync(process.execPath, [cliPath, ...args], {
      cwd: repoRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return {status: 0, stdout, stderr: ''};
  } catch (error) {
    // execFileSync exposes status/stdout/stderr on its error; decode the process
    // result at this I/O boundary instead of narrowing an unparsed value.
    return {
      status: error.status ?? 1,
      stdout: String(error.stdout ?? ''),
      stderr: String(error.stderr ?? ''),
    };
  }
}

test('accepts canonical v2 resource shapes', () => {
  assert.deepEqual(classifyV2Path('GET', '/api/v2/readingLists'), []);
  assert.deepEqual(classifyV2Path('GET', '/api/v2/readingLists/{listId}'), []);
  assert.deepEqual(classifyV2Path('PATCH', '/api/v2/readingLists/{listId}'), []);
  assert.deepEqual(classifyV2Path('GET', '/api/v2/threads/{threadId}/issues'), []);
  assert.deepEqual(classifyV2Path('POST', '/api/v2/threads'), []);
  assert.deepEqual(classifyV2Path('GET', '/api/v2/activity'), []);
});

test('accepts justified :camelCase custom methods', () => {
  assert.deepEqual(
    classifyV2Path('POST', '/api/v2/readingLists/{listId}:planAdoption'),
    [],
  );
  assert.deepEqual(classifyV2Path('GET', '/api/v2/threads:checkDuplicates'), []);
});

test('rejects a newly introduced hyphenated collection', () => {
  assert.deepEqual(classifyV2Path('GET', '/api/v2/reading-lists2'), [
    'non-lowercamelcase-segment',
  ]);
  assert.deepEqual(classifyV2Path('POST', '/api/v2/reading_lists'), [
    'non-lowercamelcase-segment',
  ]);
});

test('rejects a custom method on a non-lowerCamelCase collection', () => {
  assert.deepEqual(
    classifyV2Path('POST', '/api/v2/reading-lists2:planAdoption'),
    ['non-lowercamelcase-segment'],
  );
  assert.deepEqual(
    classifyV2Path('POST', '/api/v2/reading_order_groups:resolveMemberships'),
    ['non-lowercamelcase-segment'],
  );
  assert.deepEqual(
    classifyV2Path('POST', '/api/v2/readingLists/{listId}:planAdoption'),
    [],
  );
});

test('rejects rejected shape variants', () => {
  assert.deepEqual(classifyV2Path('GET', '/api/v2/readingLists/'), [
    'trailing-slash',
  ]);
  assert.deepEqual(classifyV2Path('POST', '/api/v2/readingLists/{listId}/restore'), [
    'action-shaped-subpath',
  ]);
  assert.deepEqual(classifyV2Path('PUT', '/api/v2/readingLists/{listId}'), [
    'put-mutation',
  ]);
  assert.deepEqual(
    classifyV2Path('POST', '/api/v2/readingLists/{listId}:PlanAdoption'),
    ['custom-method-not-lowercamelcase'],
  );
  assert.deepEqual(
    classifyV2Path('DELETE', '/api/v2/readingLists/{listId}:planAdoption'),
    ['custom-method-verb'],
  );
  assert.deepEqual(
    classifyV2Path('POST', '/api/v2/readingLists:planAdoption/items'),
    ['custom-method-not-final'],
  );
});

test('ignores v1 and unversioned operations', () => {
  assert.deepEqual(classifyV2Path('PUT', '/api/v1/threads/{thread_id}'), []);
  assert.deepEqual(classifyV2Path('POST', '/api/unversioned/path'), []);
});

test('baselined violations are accepted and unbounded ones fail', () => {
  const baseline = new Map([
    [
      'GET /api/v2/reading-lists',
      {
        method: 'GET',
        path: '/api/v2/reading-lists',
        owning_issue: 4684,
        reason: 'non-lowercamelcase-segment',
      },
    ],
  ]);
  const operations = [
    {
      method: 'GET',
      path: '/api/v2/reading-lists',
      owning_issue: 4684,
      source: 'docs/api/route-fragments/custom-cbl.json',
    },
    {
      method: 'GET',
      path: '/api/v2/reading-lists2',
      owning_issue: 5720,
      source: 'docs/api/route-fragments/custom-cbl.json',
    },
    {
      method: 'GET',
      path: '/api/v2/readingLists',
      owning_issue: 4684,
      source: 'docs/api/route-fragments/custom-cbl.json',
    },
  ];
  const {unexpected, stale} = evaluateOperations(operations, baseline);
  assert.equal(unexpected.length, 1);
  assert.equal(unexpected[0].path, '/api/v2/reading-lists2');
  assert.deepEqual(stale, []);
});

test('stale baseline entries are reported but not fatal', () => {
  const baseline = new Map([
    [
      'GET /api/v2/reading-lists',
      {
        method: 'GET',
        path: '/api/v2/reading-lists',
        owning_issue: 4684,
        reason: 'non-lowercamelcase-segment',
      },
    ],
  ]);
  const operations = [
    {
      method: 'GET',
      path: '/api/v2/readingLists',
      owning_issue: 4684,
      source: 'docs/api/route-fragments/custom-cbl.json',
    },
  ];
  const {unexpected, stale} = evaluateOperations(operations, baseline);
  assert.deepEqual(unexpected, []);
  assert.equal(stale.length, 1);
});

test('rejects anonymous or duplicate baseline exemptions', () => {
  const root = writeFixture({
    'baseline-missing-owner.json': JSON.stringify({
      entries: [{method: 'GET', path: '/api/v2/reading-lists', reason: 'x'}],
    }),
    'baseline-duplicate.json': JSON.stringify({
      entries: [
        {
          method: 'GET',
          path: '/api/v2/reading-lists',
          owning_issue: 4684,
          reason: 'x',
        },
        {
          method: 'GET',
          path: '/api/v2/reading-lists',
          owning_issue: 4684,
          reason: 'x',
        },
      ],
    }),
  });
  try {
    assert.throws(
      () => loadBaseline(path.join(root, 'baseline-missing-owner.json')),
      /needs an owning_issue/,
    );
    assert.throws(
      () => loadBaseline(path.join(root, 'baseline-duplicate.json')),
      /duplicate entry/,
    );
  } finally {
    removeFixture(root);
  }
});

test('a rendered baseline accepts exactly the current violations', () => {
  const operations = [
    {
      method: 'GET',
      path: '/api/v2/reading-lists',
      owning_issue: 4684,
      source: 'docs/api/route-fragments/custom-cbl.json',
    },
    {
      method: 'PUT',
      path: '/api/v2/reading-mode',
      owning_issue: null,
      source: 'docs/api/route-fragments/reading-mode.json',
    },
    {
      method: 'GET',
      path: '/api/v2/readingLists',
      owning_issue: 4684,
      source: 'docs/api/route-fragments/custom-cbl.json',
    },
  ];
  const {violations} = evaluateOperations(operations, new Map());
  assert.equal(violations.length, 2);
  const root = writeFixture({'baseline.json': renderBaseline(violations, 4335)});
  try {
    const baseline = loadBaseline(path.join(root, 'baseline.json'));
    assert.equal(baseline.size, 2);
    assert.equal(baseline.get('PUT /api/v2/reading-mode').owning_issue, 4335);
    const second = evaluateOperations(operations, baseline);
    assert.deepEqual(second.unexpected, []);
    assert.deepEqual(second.stale, []);
  } finally {
    removeFixture(root);
  }
});

test('loads fragments and the generated inventory for one operation set', () => {
  const root = writeFixture({
    'fragments/threads.json': JSON.stringify({
      defaults: {owning_issue: 4342},
      operations: [
        {method: 'GET', path: '/api/v2/threads'},
        {method: 'GET', path: '/api/v2/threads/{thread_id}/issues', owning_issue: 5706},
      ],
    }),
    'fragments/vercel-rewrites.json': JSON.stringify({
      operations: [{method: 'GET', path: '/api/v2/ignored-generated-route'}],
    }),
    'inventory.json': JSON.stringify({
      operations: [
        {method: 'GET', path: '/api/v2/threads'},
        {method: 'GET', path: '/api/v2/auth/me', owning_issue: 4459},
      ],
    }),
  });
  try {
    const fragments = loadFragmentOperations(path.join(root, 'fragments'));
    assert.equal(fragments.length, 2);
    assert.equal(fragments[1].owning_issue, 5706);
    assert.equal(fragments[0].owning_issue, 4342);
    const inventory = loadInventoryOperations(path.join(root, 'inventory.json'));
    const merged = mergeOperations(fragments, inventory);
    assert.deepEqual(
      merged.map(operation => `${operation.method} ${operation.path}`).sort(),
      ['GET /api/v2/auth/me', 'GET /api/v2/threads', 'GET /api/v2/threads/{thread_id}/issues'],
    );
  } finally {
    removeFixture(root);
  }
});

test('repository fragments and inventory satisfy the committed baseline', () => {
  const result = runCli([]);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /0 new violation/);
});

test('the CLI fails a new non-AIP route and prints it', () => {
  const root = writeFixture({
    'fragments/reading-lists.json': JSON.stringify({
      operations: [
        {method: 'GET', path: '/api/v2/readingLists', owning_issue: 4684},
        {method: 'GET', path: '/api/v2/reading-lists2', owning_issue: 5720},
      ],
    }),
    'inventory.json': JSON.stringify({operations: []}),
  });
  try {
    const result = runCli([
      '--fragments', path.join(root, 'fragments'),
      '--inventory', path.join(root, 'inventory.json'),
      '--baseline', baselinePath,
    ]);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /GET \/api\/v2\/reading-lists2/);
    assert.match(result.stderr, /AIP-122/);
  } finally {
    removeFixture(root);
  }
});
