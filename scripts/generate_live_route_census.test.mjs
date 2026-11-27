import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  callerMatchesRoute,
  CBL_ROUTE_DISPOSITIONS,
  CBL_ROUTE_OWNER,
  generate,
  normalizeCallerPath,
  parseRouterRoutes,
  pathsMatch,
  scanCallers,
} from './generate_live_route_census.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const script = path.join(repoRoot, 'scripts', 'generate_live_route_census.mjs');
const fixturesRoot = path.join(repoRoot, 'scripts', '__fixtures__', 'live-route-census');
const inputsRoot = path.join(fixturesRoot, 'inputs');
const goldenRoot = path.join(fixturesRoot, 'golden');
const ARTIFACTS = [
  'docs/api/live-route-census.json',
  'docs/api/v1-retirement-allowlist.json',
  'docs/api/LIVE_ROUTE_CENSUS.md',
];

/** Stage hermetic fixture inputs into a temporary repository root. */
function stage(tmp) {
  cpSync(inputsRoot, tmp, {recursive: true});
  return tmp;
}

function run(root, ...args) {
  return execFileSync(process.execPath, [script, '--root', root, ...args], {
    cwd: repoRoot,
    encoding: 'utf8',
  });
}

test('router parser records live registrations and ignores test-module strings', () => {
  const source = readFileSync(path.join(inputsRoot, 'native/roll-service/src/lib.rs'), 'utf8');
  const routes = parseRouterRoutes(source);
  assert.equal(routes.length, 6);
  const restore = routes.find(route => route.path.endsWith('/restore'));
  assert.deepEqual(
    {method: restore.method, handler: restore.handler, line: restore.line},
    {method: 'POST', handler: 'thread_lifecycle::restore_thread', line: 7},
  );
  assert.ok(!routes.some(route => route.path === '/api/v1/threads/7/restore'));
  const inline = routes.find(route => route.path === '/health');
  assert.equal(inline.handler, '<inline>');
  const {census} = generate(inputsRoot);
  assert.ok(!census.routes.some(route => route.path === '/health'), 'non-API routes are outside the census');
});

test('path and HTTP-method matching are independent and deterministic', () => {
  assert.equal(normalizeCallerPath('/v1/threads/${id}/restore'), '/api/v1/threads/{param}/restore');
  assert.equal(normalizeCallerPath('/api/v1/threads/stale?page=2'), '/api/v1/threads/stale');
  assert.ok(pathsMatch('/api/v1/threads/{param}/restore', '/api/v1/threads/{thread_id}/restore'));
  assert.ok(!pathsMatch('/api/v1/threads/stale', '/api/v1/threads/{thread_id}/restore'));
  assert.ok(!pathsMatch('/api/v1/threads/stale/extra', '/api/v1/threads/stale'));
  const route = {method: 'POST', path: '/api/v1/threads/{thread_id}/restore'};
  assert.ok(callerMatchesRoute({method: 'POST', path: '/api/v1/threads/{param}/restore'}, route));
  assert.ok(!callerMatchesRoute({method: 'GET', path: '/api/v1/threads/{param}/restore'}, route));
  assert.ok(callerMatchesRoute({method: '', path: '/api/v1/threads/7/restore'}, route));
});

test('caller scan excludes generated, type and fixture references', () => {
  const callers = scanCallers(inputsRoot);
  const paths = callers.map(caller => caller.path);
  assert.ok(!paths.some(callerPath => callerPath.includes('retired-fixture-only')));
  assert.ok(!callers.some(caller => caller.file.startsWith('frontend/src/generated/')));
  assert.ok(callers.some(caller => caller.file === 'frontend/src/services/api-threads.ts'));
  assert.ok(callers.some(caller => caller.file === 'scripts/ops/cli.mjs'));
  assert.ok(callers.some(caller => caller.file === 'frontend/src/test/api.spec.ts'));
  assert.equal(
    callers.filter(caller => caller.drift_checked).length,
    3,
    'generated/fixture references and synthetic spec data are not drift sources',
  );
});

test('generator matches golden fixtures and --check detects drift', t => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'live-census-golden-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));
  stage(tmp);
  run(tmp);

  for (const artifact of ARTIFACTS) {
    assert.deepEqual(
      readFileSync(path.join(tmp, artifact)),
      readFileSync(path.join(goldenRoot, path.basename(artifact))),
      `${artifact} differs from the golden fixture`,
    );
  }
  assert.match(run(tmp, '--check'), /Verified live route census/);

  // A freshly generated tree is stable across runs.
  const first = readFileSync(path.join(tmp, ARTIFACTS[0]), 'utf8');
  run(tmp);
  assert.equal(readFileSync(path.join(tmp, ARTIFACTS[0]), 'utf8'), first);

  writeFileSync(path.join(tmp, ARTIFACTS[0]), `${first}\n`);
  assert.throws(() => run(tmp, '--check'), error => error.status === 1);
});

test('the retired direct thread-selection route is absent from the live census', () => {
  const fixture = JSON.parse(readFileSync(path.join(goldenRoot, 'live-route-census.json'), 'utf8'));
  const checkedIn = JSON.parse(readFileSync(path.join(repoRoot, 'docs/api/live-route-census.json'), 'utf8'));
  for (const census of [fixture, checkedIn]) {
    assert.ok(!census.routes.some(item => item.path.endsWith('/pending')));
    assert.ok(!census.routes.some(item => item.handler?.includes('set_pending')));
  }
});

test('CBL comparison and candidate discovery stay pinned to #5713', () => {
  const census = JSON.parse(readFileSync(path.join(repoRoot, 'docs/api/live-route-census.json'), 'utf8'));
  const report = readFileSync(path.join(repoRoot, 'docs/api/LIVE_ROUTE_CENSUS.md'), 'utf8');
  const dispositions = JSON.parse(
    readFileSync(path.join(repoRoot, 'docs/api/v1-route-dispositions.json'), 'utf8'),
  );
  assert.match(report, /#5713/, 'the owner cross-reference must include #5713');
  for (const [key, expectedDisposition] of CBL_ROUTE_DISPOSITIONS) {
    const override = dispositions.overrides[key];
    assert.ok(override, `${key} must have an explicit disposition override`);
    assert.equal(override.owner_issue, CBL_ROUTE_OWNER);
    assert.equal(override.replacement, expectedDisposition);
    const route = census.routes.find(item => `${item.method} ${item.path}` === key);
    assert.ok(route, `${key} must be a live census row`);
    assert.equal(route.owner_issue, CBL_ROUTE_OWNER);
    assert.equal(route.disposition, expectedDisposition);
    assert.equal(route.needs_owner_issue, false);
  }
  const compare = census.routes.find(route => route.path === '/api/v1/issue-identity/cbl-sources/compare');
  assert.equal(compare.method, 'POST', 'HTTP method must be part of the cross-reference pin');
  assert.notEqual(compare.owner_issue, 5712, 'the #5712 catalog-list family must not own the compare POST');
  const candidates = census.routes.find(route =>
    route.path === '/api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates');
  assert.notEqual(candidates.owner_issue, 4844, 'the #4844 adoption family must not own candidate discovery');
});

test('published report cross-references every mandated owner issue', () => {
  const report = readFileSync(path.join(repoRoot, 'docs/api/LIVE_ROUTE_CENSUS.md'), 'utf8');
  const mandated = [
    ...Array.from({length: 18}, (_, index) => 5701 + index),
    4341, 4343, 4549, 4299,
  ];
  for (const issue of mandated) {
    assert.match(report, new RegExp(`#${issue}\\b`), `report must cross-reference #${issue}`);
  }
});

test('every current live v1 method has an owner and a disposition', () => {
  const census = JSON.parse(readFileSync(path.join(repoRoot, 'docs/api/live-route-census.json'), 'utf8'));
  const allowlist = JSON.parse(
    readFileSync(path.join(repoRoot, 'docs/api/v1-retirement-allowlist.json'), 'utf8'),
  );
  const v1 = census.routes.filter(route => route.version === 'v1');
  assert.ok(v1.length > 0);
  for (const route of v1) {
    assert.ok(Number.isInteger(route.owner_issue) && route.owner_issue > 0, `${route.path} has no owner`);
    assert.ok(route.disposition && route.disposition !== 'needs-owner-disposition', `${route.path} has no disposition`);
    assert.equal(route.needs_owner_issue, false, `${route.path} is unowned baseline drift`);
    assert.ok(
      allowlist.entries.some(entry => entry.method === route.method && entry.path === route.path),
      `${route.method} ${route.path} is missing from the retirement allowlist`,
    );
  }
  assert.equal(census.summary.v1_needing_owner, 0);
});

test('CI gate rejects a new first-party v1 call', t => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'live-census-new-call-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));
  stage(tmp);
  const service = path.join(tmp, 'frontend/src/services/api-threads.ts');
  writeFileSync(service, `${readFileSync(service, 'utf8')}\nclient.get('/v1/threads/never-owned')\n`);
  const failures = generate(tmp).failures;
  assert.ok(
    failures.some(failure => failure.includes('/v1/threads/never-owned')),
    `expected a new-v1-call failure, got ${JSON.stringify(failures)}`,
  );
});

test('CI gate rejects an unowned v1 route registration', t => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'live-census-unowned-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));
  stage(tmp);
  const router = path.join(tmp, 'native/roll-service/src/lib.rs');
  const source = readFileSync(router, 'utf8').replace(
    '.route("/health", get(|| async { "ok" }))',
    '.route("/health", get(|| async { "ok" }))\n        .route("/api/v1/unowned/new", post(mystery::handler))',
  );
  writeFileSync(router, source);
  const failures = generate(tmp).failures;
  assert.ok(failures.some(failure => failure.includes('/api/v1/unowned/new')), JSON.stringify(failures));
});

test('CI gate rejects unresolved ingress and stale baseline debt', t => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'live-census-ingress-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));
  stage(tmp);
  writeFileSync(path.join(tmp, 'vercel.json'), '{"routes":[]}\n');
  const dispositionsPath = path.join(tmp, 'docs/api/v1-route-dispositions.json');
  const dispositions = JSON.parse(readFileSync(dispositionsPath, 'utf8'));
  dispositions.known_unowned_baseline = ['GET /api/v1/retired'];
  writeFileSync(dispositionsPath, `${JSON.stringify(dispositions, null, 2)}\n`);
  const failures = generate(tmp).failures;
  assert.ok(failures.some(failure => failure.includes('no production ingress')), JSON.stringify(failures));
  assert.ok(failures.some(failure => failure.includes('known baseline debt')), JSON.stringify(failures));
});

test('fixture artifacts are complete and checked-in outputs are current', () => {
  for (const artifact of ARTIFACTS) {
    assert.ok(existsSync(path.join(goldenRoot, path.basename(artifact))));
    assert.ok(existsSync(path.join(repoRoot, artifact)));
  }
  const check = execFileSync(process.execPath, [script, '--check'], {cwd: repoRoot, encoding: 'utf8'});
  assert.match(check, /Verified live route census/);
});

