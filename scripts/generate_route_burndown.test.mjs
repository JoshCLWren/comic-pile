import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {
  copyFileSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {pythonJsonDumps} from './generate_route_burndown.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nodeScript = path.join(repoRoot, 'scripts', 'generate_route_burndown.mjs');
const fixturesRoot = path.join(repoRoot, 'scripts', '__fixtures__', 'route-burndown');
const fixtureInputs = path.join(fixturesRoot, 'inputs');
const fixtureGolden = path.join(fixturesRoot, 'golden');

const GOLDEN_BY_KEY = {
  inventory: 'inventory.json',
  vercel: 'vercel.json',
  agents: 'AGENTS.md',
  rewrite: 'vercel-rewrites.json',
};

/**
 * Stage the checked-in hermetic fixture inputs into a temp working directory.
 *
 * The generator reads `docs/api/sql-budget-sources.json` relative to cwd, so
 * the staged layout must include that path. Nothing here reads the live
 * `vercel.json`, inventory, AGENTS.md, or route fragments: fragment-only route
 * PRs intentionally leave those bot-owned artifacts stale until post-merge
 * regeneration, so comparing against them would fail every such PR in the
 * `factory-pr-auth` job (which does not regenerate before running these tests).
 *
 * @param {string} tmp Temp directory root.
 * @returns {object} Paths to the staged input/output files and fragments dir.
 */
function stageInputs(tmp) {
  const fragments = path.join(tmp, 'fragments');
  mkdirSync(path.join(tmp, 'docs', 'api'), {recursive: true});
  cpSync(path.join(fixtureInputs, 'fragments'), fragments, {recursive: true});
  for (const file of Object.values(GOLDEN_BY_KEY)) {
    copyFileSync(path.join(fixtureInputs, file), path.join(tmp, file));
  }
  copyFileSync(
    path.join(fixtureInputs, 'sql-budget-sources.json'),
    path.join(tmp, 'docs', 'api', 'sql-budget-sources.json'),
  );
  return {
    inventory: path.join(tmp, 'inventory.json'),
    vercel: path.join(tmp, 'vercel.json'),
    agents: path.join(tmp, 'AGENTS.md'),
    rewrite: path.join(tmp, 'vercel-rewrites.json'),
    fragments,
  };
}

function generatorArgs(files) {
  return [
    '--inventory', files.inventory,
    '--fragments', files.fragments,
    '--rewrite-fragment', files.rewrite,
    '--vercel', files.vercel,
    '--agents', files.agents,
  ];
}

function run(scriptCmd, args, cwd) {
  execFileSync(scriptCmd[0], [...scriptCmd.slice(1), ...args], {cwd, encoding: 'utf8'});
}

function readBytes(filePath) {
  return readFileSync(filePath);
}

test('pythonJsonDumps escapes non-ASCII like Python ensure_ascii=True', () => {
  const text = pythonJsonDumps({s: 'café 😀'});
  assert.ok(text.includes('\\u00e9'), `expected \\u00e9 in ${text}`);
  assert.ok(text.includes('\\ud83d\\ude00'), `expected surrogate pair in ${text}`);
  assert.ok(!text.includes('é'), 'non-ASCII char must be escaped');
  assert.ok(!text.includes('😀'), 'astral char must be escaped');
});

test('node generator matches checked-in golden fixtures on hermetic inputs', (t) => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'route-burndown-golden-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));

  const files = stageInputs(tmp);
  run([process.execPath, nodeScript], generatorArgs(files), tmp);

  for (const [key, golden] of Object.entries(GOLDEN_BY_KEY)) {
    assert.deepEqual(
      readBytes(files[key]),
      readBytes(path.join(fixtureGolden, golden)),
      `${golden} differs from the checked-in golden fixture`,
    );
  }

  // Staleness detection is exercised against fixtures too: a freshly generated
  // tree passes --check, and mutating one output makes it fail with exit 1.
  const checkArgs = [...generatorArgs(files), '--check'];
  run([process.execPath, nodeScript], checkArgs, tmp);
  writeFileSync(files.inventory, `${readFileSync(files.inventory, 'utf8')}\n`);
  assert.throws(() => run([process.execPath, nodeScript], checkArgs, tmp), err => err.status === 1);
});


test('generator rejects invalid fragment input and leaves fixtures untouched', (t) => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'route-burndown-invalid-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));

  const files = stageInputs(tmp);
  writeFileSync(
    path.join(files.fragments, 'invalid.json'),
    `${JSON.stringify({
      family: 'invalid',
      owned_path_patterns: ['^/api/v2/bad$'],
      defaults: {},
      operations: [{bucket: 'operations', method: 'GET', path: '/api/v2/bad', dest: '/api/bad'}],
    }, null, 2)}\n`,
  );

  assert.throws(
    () => run([process.execPath, nodeScript], generatorArgs(files), tmp),
    err => err.status === 2,
  );
  assert.deepEqual(
    readBytes(files.inventory),
    readBytes(path.join(fixtureInputs, 'inventory.json')),
    'rejected input must not modify the staged inventory',
  );
});

/**
 * Real source-fragment regression checks. The fixture tests above prove the
 * generator is deterministic; these prove active route declarations retain
 * their intended contracts before bot-owned outputs regenerate post-merge.
 * Ported from tests/test_route_burndown.py when the Python tool was retired.
 */
function liveFragment(name) {
  return JSON.parse(readFileSync(path.join(repoRoot, 'docs/api/route-fragments', name + '.json'), 'utf8'));
}

function liveOperation(fragment, method, route) {
  const op = fragment.operations.find(item => item.method === method && item.path === route);
  assert.ok(op, 'missing ' + method + ' ' + route + ' from ' + fragment.family);
  return op;
}

test('real creator source retains all eleven native v2 browser routes', () => {
  const fragment = liveFragment('creators');
  const routes = fragment.operations.filter(op => op.path.startsWith('/api/v2/creators'));
  assert.equal(routes.length, 11);
  assert.equal(new Set(routes.map(op => op.method + ' ' + op.path)).size, 11);
  for (const op of routes) {
    assert.equal(op.bucket, 'operations', op.path);
    assert.equal(op.method, 'GET', op.path);
    assert.equal(op.dest, '/api/native_roll.rs', op.path);
    assert.equal(op.runtime, 'native-rust', op.path);
    assert.equal(op.status, 'target', op.path);
    assert.equal(op.owning_issue, 4836, op.path);
  }
  for (const route of [
    '/api/v2/creators',
    '/api/v2/creators/{creator_key}',
    '/api/v2/creators/{creator_key}/series/{series_key}/issues',
  ]) {
    liveOperation(fragment, 'GET', route);
  }
  assert.equal(liveOperation(fragment, 'GET', '/api/v1/threads/{thread_id}/issues/creators').dest, '/api/native_roll.rs');
});

test('real custom CBL source retains native reading-list route ownership', () => {
  const fragment = liveFragment('custom-cbl');
  assert.equal(fragment.operations.length, 15);
  assert.deepEqual(new Set(fragment.operations.map(op => op.bucket)), new Set(['operations']));
  assert.ok(!fragment.operations.some(op => op.method === 'OPTIONS'));
  for (const op of fragment.operations) {
    assert.equal(op.dest, '/api/native_roll.rs', op.path);
    assert.equal(op.runtime, 'native-rust', op.path);
    assert.ok([4684, 4844, 5435].includes(op.owning_issue), op.path + ' owning_issue=' + op.owning_issue);
  }
  for (const [method, route, owningIssue] of [
    ['GET', '/api/v2/reading-lists', 4684],
    ['POST', '/api/v2/reading-lists', 4684],
    ['POST', '/api/v2/reading-lists/memberships:check', 5435],
    ['GET', '/api/v2/reading-lists/{list_id}', 4684],
    ['PUT', '/api/v2/reading-lists/{list_id}', 4684],
    ['DELETE', '/api/v2/reading-lists/{list_id}', 4684],
    ['GET', '/api/v2/reading-lists/{list_id}/reader', 4684],
    ['GET', '/api/v2/reading-lists/issue-candidates', 4844],
    ['GET', '/api/v2/reading-lists/{list_id}/export', 4844],
    ['POST', '/api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/applications', 4844],
    ['GET', '/api/v2/reading-lists/{list_id}/overlap-decisions', 4844],
    ['PUT', '/api/v2/reading-lists/{list_id}/overlap-decisions', 4844],
    ['DELETE', '/api/v2/reading-lists/{list_id}/overlap-decisions/{decision_id}', 4844],
  ]) {
    const op = liveOperation(fragment, method, route);
    assert.equal(op.owning_issue, owningIssue, route);
  }
  for (const [method, route] of [
    ['POST', '/api/v2/reading-lists/{list_id}/adoption-commits'],
    ['POST', '/api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/adoption-commits'],
  ]) {
    const op = liveOperation(fragment, method, route);
    assert.equal(op.owning_issue, 4844, route);
  }
});

test('real taste and bug-report fragments cannot regress to Python ingress', () => {
  const taste = liveFragment('taste-discoveries');
  assert.equal(taste.operations.length, 2);
  liveOperation(taste, 'GET', '/api/v1/taste/discoveries');
  liveOperation(taste, 'POST', '/api/v1/taste/discoveries/{signal_id}/dismiss');
  assert.ok(!taste.operations.some(op => op.method === 'OPTIONS'));
  assert.equal(taste.defaults.runtime, 'native-rust');
  for (const op of taste.operations) assert.equal(op.dest, '/api/native_roll.rs', op.path);

  const bugs = liveFragment('bug-reports');
  assert.deepEqual(
    new Set(bugs.operations.map(op => op.method + ' ' + op.path)),
    new Set(['POST /api/bug-reports/', 'POST /api/v1/bug-reports/']),
  );
  for (const op of bugs.operations) {
    assert.equal(op.dest, '/api/native_roll.rs', op.path);
    assert.equal(op.exclude_from_inventory, true, op.path);
    assert.equal(op.owning_issue, 4852, op.path);
  }
});

test('real session and undo fragments retain native-only supported operations', () => {
  const sessions = liveFragment('sessions');
  const undo = liveFragment('undo');

  // Session details/snapshots moved to the resource-shaped v2 surface; the
  // legacy v1/unversioned single-session and list reads are retired (#4343,
  // #4839). Undo snapshots/restore are served on the native v2 surface.
  const expectedSessions = [
    ['GET', '/api/v2/reading-sessions/{session_id}/details'],
    ['GET', '/api/v2/reading-sessions/{session_id}/snapshots'],
  ];
  const undoExpected = [
    ['GET', '/api/v2/undo/{session_id}/snapshots'],
    ['POST', '/api/v2/undo/{session_id}/snapshots/{snapshot_id}/restore'],
  ];

  assert.equal(sessions.operations.length, expectedSessions.length);
  for (const [method, route] of expectedSessions) {
    const op = liveOperation(sessions, method, route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    assert.equal(op.bucket, 'operations', route);
    assert.ok(op.consumers.includes('frontend/src/services/api-sessions.ts'), route);
  }

  assert.equal(undo.operations.length, undoExpected.length);
  for (const [method, route] of undoExpected) {
    const op = liveOperation(undo, method, route);
    assert.equal(op.bucket, 'operations', route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    assert.equal(op.runtime, 'native-rust', route);
    assert.equal(op.owning_issue, 4839, route);
  }

  assert.ok(![...sessions.operations, ...undo.operations].some(
    op => op.path.includes('current-session') || op.path.includes('restore-session-start'),
  ));
  assert.ok(!sessions.operations.some(
    op => op.path.startsWith('/api/v1/sessions') || op.path.startsWith('/api/sessions'),
  ));
});

test('real releases and dependency fragments retain declared browser routes', () => {
  const releases = liveFragment('releases');
  const expectedReleases = [
    ['GET', '/api/v2/releases'],
    ['PUT', '/api/v1/releases/'],
    ['GET', '/api/v1/releases/source'],
    ['GET', '/api/v1/releases/{release_id}'],
    ['POST', '/api/v1/releases/{release_id}/retract'],
  ];
  assert.equal(releases.operations.length, expectedReleases.length);
  for (const [method, route] of expectedReleases) {
    const op = liveOperation(releases, method, route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    if (route === '/api/v2/releases') {
      assert.equal(op.bucket, 'operations', route);
      assert.ok(op.consumers.includes('frontend/src/services/api-releases.ts'), route);
    } else {
      assert.equal(op.exclude_from_inventory, true, route);
    }
  }
  const dependencies = liveFragment('dependencies');
  assert.deepEqual(new Set(dependencies.operations.map(op => op.bucket)), new Set(['operations', 'v1_operations']));
  for (const [method, route] of [
    ['POST', '/api/v2/dependencies/'],
    ['DELETE', '/api/v2/dependencies/{dependency_id}'],
  ]) {
    const op = liveOperation(dependencies, method, route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    assert.equal(op.runtime, 'native-rust', route);
  }
});

test('retired identity-inbox handlers retain all seven native same-path contracts', () => {
  const native = JSON.parse(readFileSync(
    path.join(repoRoot, 'native/contracts/same-path-runtime.openapi.json'), 'utf8',
  ));
  const expected = [
    ['GET', '/api/v1/identity-inbox'],
    ['GET', '/api/v1/identity-inbox/search/issues'],
    ['GET', '/api/v1/identity-inbox/{mapping_id}'],
    ['POST', '/api/v1/identity-inbox/{mapping_id}/confirm'],
    ['POST', '/api/v1/identity-inbox/{mapping_id}/defer'],
    ['POST', '/api/v1/identity-inbox/{mapping_id}/reject'],
    ['POST', '/api/v1/identity-inbox/{mapping_id}/skip'],
  ];
  for (const [method, route] of expected) {
    const op = native.paths[route]?.[method.toLowerCase()];
    assert.ok(op?.operationId, 'missing native operationId for ' + method + ' ' + route);
    assert.ok(Object.keys(op.responses).some(code => code.startsWith('2')), route);
  }
});
