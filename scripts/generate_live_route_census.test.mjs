import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  callerMatchesRoute,
  generate,
  normalizeCallerPath,
  parseRouterRoutes,
  pathsMatch,
  scanCallers,
  SET_PENDING_OWNER,
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
  assert.equal(routes.length, 5);
  const setPending = routes.find(route => route.path.endsWith('/set-pending'));
  assert.deepEqual(
    {method: setPending.method, handler: setPending.handler, line: setPending.line},
    {method: 'POST', handler: 'thread_lifecycle::set_pending_thread', line: 7},
  );
  assert.ok(!routes.some(route => route.path === '/api/v1/threads/7/set-pending'));
  const inline = routes.find(route => route.path === '/health');
  assert.equal(inline.handler, '<inline>');
  const {census} = generate(inputsRoot);
  assert.ok(!census.routes.some(route => route.path === '/health'), 'non-API routes are outside the census');
});

test('path and HTTP-method matching are independent and deterministic', () => {
  assert.equal(normalizeCallerPath('/v1/threads/${id}/set-pending'), '/api/v1/threads/{param}/set-pending');
  assert.equal(normalizeCallerPath('/api/v1/threads/stale?page=2'), '/api/v1/threads/stale');
  assert.ok(pathsMatch('/api/v1/threads/{param}/set-pending', '/api/v1/threads/{thread_id}/set-pending'));
  assert.ok(!pathsMatch('/api/v1/threads/stale', '/api/v1/threads/{thread_id}/set-pending'));
  assert.ok(!pathsMatch('/api/v1/threads/stale/extra', '/api/v1/threads/stale'));
  const route = {method: 'POST', path: '/api/v1/threads/{thread_id}/set-pending'};
  assert.ok(callerMatchesRoute({method: 'POST', path: '/api/v1/threads/{param}/set-pending'}, route));
  assert.ok(!callerMatchesRoute({method: 'GET', path: '/api/v1/threads/{param}/set-pending'}, route));
  assert.ok(callerMatchesRoute({method: '', path: '/api/v1/threads/7/set-pending'}, route));
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
    4,
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

test('set-pending stays in the census because Rust implementation is not v1 retirement', () => {
  const fixture = JSON.parse(readFileSync(path.join(goldenRoot, 'live-route-census.json'), 'utf8'));
  const checkedIn = JSON.parse(readFileSync(path.join(repoRoot, 'docs/api/live-route-census.json'), 'utf8'));
  for (const census of [fixture, checkedIn]) {
    const route = census.routes.find(item =>
      item.method === 'POST' && item.path === '/api/v1/threads/{thread_id}/set-pending');
    assert.ok(route, 'Rust-served v1 set-pending must be counted, not omitted');
    assert.equal(route.version, 'v1');
    assert.equal(route.runtime, 'native-rust');
    assert.equal(route.owner_issue, SET_PENDING_OWNER);
    assert.equal(route.disposition, 'retire-without-replacement');
    assert.match(route.handler, /set_pending_thread/);
  }
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

test('CI gate rejects unresolved ingress and stale allowlist debt', t => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'live-census-ingress-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));
  stage(tmp);
  writeFileSync(path.join(tmp, 'vercel.json'), '{"routes":[]}\n');
  const failures = generate(tmp).failures;
  assert.ok(failures.some(failure => failure.includes('no production ingress')), JSON.stringify(failures));
  assert.ok(failures.some(failure => failure.includes('missing from the retirement allowlist')));
});

test('fixture artifacts are complete and checked-in outputs are current', () => {
  for (const artifact of ARTIFACTS) {
    assert.ok(existsSync(path.join(goldenRoot, path.basename(artifact))));
    assert.ok(existsSync(path.join(repoRoot, artifact)));
  }
  const check = execFileSync(process.execPath, [script, '--check'], {cwd: repoRoot, encoding: 'utf8'});
  assert.match(check, /Verified live route census/);
});

