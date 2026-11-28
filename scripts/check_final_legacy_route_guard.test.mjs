import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {test} from 'node:test';

import {
  ALLOWLIST,
  collectViolations,
  DEFAULT_ROOT,
  FRAGMENT_DIR,
  INGRESS_ROUTER,
  INNER_ROUTER,
  isLegacyPath,
  main,
  parseRegisteredRoutes,
} from './check_final_legacy_route_guard.mjs';

/** Build the smallest repository shape the guard reads. */
function makeRoot(t) {
  const root = mkdtempSync(path.join(tmpdir(), 'final-route-guard-'));
  t.after(() => rmSync(root, {recursive: true, force: true}));
  for (const dir of [
    path.dirname(path.join(root, INNER_ROUTER)),
    path.dirname(path.join(root, INGRESS_ROUTER)),
    path.join(root, FRAGMENT_DIR),
  ]) {
    mkdirSync(dir, {recursive: true});
  }
  writeFileSync(
    path.join(root, INNER_ROUTER),
    'fn router() {\n  Router::new().route("/api/v1/creators", get(h))\n}\n',
  );
  writeFileSync(
    path.join(root, INGRESS_ROUTER),
    'fn app() {\n  Router::new().route("/api/v1/creators", get(dispatch))\n}\n',
  );
  writeFileSync(
    path.join(root, ALLOWLIST),
    JSON.stringify({
      entries: [{method: 'GET', path: '/api/v1/creators', version: 'v1'}],
    }),
  );
  writeFileSync(
    path.join(root, FRAGMENT_DIR, 'creators.json'),
    JSON.stringify({family: 'creators', operations: []}),
  );
  writeFileSync(
    path.join(root, 'vercel.json'),
    JSON.stringify({routes: [
      {src: '/api/v2/creators', methods: ['GET'], dest: '/api/native_roll.rs'},
      {src: '/api(?:/.*)?', dest: '/api/native_roll.rs'},
      {src: '/(.*)', dest: 'static/404.html'},
    ]}),
  );
  return root;
}

/** Insert a legacy rewrite into the fixture's checked-in Vercel document. */
function addLegacyIngress(root, src = '/api/v1/roll/dismiss-pending') {
  const file = path.join(root, 'vercel.json');
  const config = JSON.parse(readFileSync(file, 'utf8'));
  config.routes.splice(1, 0, {src, methods: ['POST'], dest: '/api/native_roll.rs'});
  writeFileSync(file, JSON.stringify(config));
}

test('path classification separates legacy aliases from v2 and metrics', () => {
  assert.equal(isLegacyPath('/api/v1/creators'), true);
  assert.equal(isLegacyPath('/api/threads/7'), true);
  assert.equal(isLegacyPath('/api/v3/thing'), true);
  assert.equal(isLegacyPath('/api/v2/creators'), false);
  assert.equal(isLegacyPath('/api/metrics'), false);
});

test('route parsing captures every verb and ignores test fixtures', () => {
  const source = [
    'fn router() {',
    '  Router::new().route("/api/v1/a", get(one).post(two))',
    '    .route("/api/v2/b", patch(three));',
    '}',
    '#[cfg(test)]',
    'mod tests {',
    '  fn fixture() { Router::new().route("/api/v1/fake", get(fake)) }',
    '}',
  ].join('\n');
  assert.deepEqual(parseRegisteredRoutes(source), [
    {method: 'GET', path: '/api/v1/a'},
    {method: 'POST', path: '/api/v1/a'},
    {method: 'PATCH', path: '/api/v2/b'},
  ]);
});

test('an owned legacy alias passes both routers and fragments', t => {
  assert.deepEqual(collectViolations(makeRoot(t)), []);
});

test('a new v1 registration in either router fails', t => {
  const root = makeRoot(t);
  for (const router of [INNER_ROUTER, INGRESS_ROUTER]) {
    const file = path.join(root, router);
    writeFileSync(
      file,
      `${readFileSync(file, 'utf8')}\n  .route("/api/v1/releases/", put(writer))\n`,
    );
    const violations = collectViolations(root);
    assert.ok(
      violations.some(v => v.includes(router) && v.includes('PUT /api/v1/releases/')),
      JSON.stringify(violations),
    );
  }
});

test('a legacy cron or fragment operation is rejected', t => {
  const root = makeRoot(t);
  const fragment = path.join(root, FRAGMENT_DIR, 'creators.json');
  writeFileSync(fragment, JSON.stringify({
    family: 'creators',
    vercel_generation: {crons: [{path: '/api/v1/cron/release-sync', schedule: '0 9 * * *'}]},
    operations: [],
  }));
  const cronViolations = collectViolations(root);
  assert.ok(cronViolations.some(v => v.includes('legacy cron target')), JSON.stringify(cronViolations));

  writeFileSync(fragment, JSON.stringify({
    family: 'creators',
    operations: [{method: 'GET', path: '/api/v1/releases/', bucket: 'v1_operations'}],
  }));
  const opViolations = collectViolations(root);
  assert.ok(
    opViolations.some(v => v.includes('legacy fragment operation')),
    JSON.stringify(opViolations),
  );
});

test('a retired rewrite src that is still registered fails', t => {
  const root = makeRoot(t);
  writeFileSync(path.join(root, FRAGMENT_DIR, 'creators.json'), JSON.stringify({
    family: 'creators',
    vercel_generation: {retired_rewrite_srcs: ['^/api/v1/creators$']},
    operations: [],
  }));
  const violations = collectViolations(root);
  assert.ok(
    violations.some(v => v.includes('retired rewrite src') && v.includes('still registered')),
    JSON.stringify(violations),
  );
});

test('a legacy src surviving Vercel regeneration fails', t => {
  const root = makeRoot(t);
  addLegacyIngress(root);
  const violations = collectViolations(root);
  assert.ok(
    violations.some(v => v.includes('registered legacy ingress')
      && v.includes('/api/v1/roll/dismiss-pending')),
    JSON.stringify(violations),
  );
  // The bare-domain alias is rejected identically.
  addLegacyIngress(root, '/api/roll/dismiss-pending');
  assert.ok(
    collectViolations(root).some(v => v.includes('registered legacy ingress')
      && v.includes('/api/roll/dismiss-pending')),
    JSON.stringify(collectViolations(root)),
  );
});

test('a declared retired rewrite src is absent from regenerated Vercel ingress', t => {
  const root = makeRoot(t);
  addLegacyIngress(root);
  const fragment = path.join(root, FRAGMENT_DIR, 'creators.json');
  const config = JSON.parse(readFileSync(fragment, 'utf8'));
  config.vercel_generation = {
    retired_rewrite_srcs: ['/api/v1/roll/dismiss-pending'],
  };
  writeFileSync(fragment, JSON.stringify(config));
  assert.deepEqual(collectViolations(root), []);
});

test('when scoped owners land an emptied allowlist rejects remaining v1 routes', t => {
  const root = makeRoot(t);
  writeFileSync(path.join(root, ALLOWLIST), JSON.stringify({entries: []}));
  const violations = collectViolations(root);
  assert.ok(violations.some(v => v.includes('GET /api/v1/creators')), JSON.stringify(violations));
});

test('the checked-in deployment surfaces pass the guard', () => {
  assert.equal(main([]), 0);
  assert.deepEqual(collectViolations(DEFAULT_ROOT), []);
});
