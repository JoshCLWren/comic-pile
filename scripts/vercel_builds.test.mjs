import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {
  assertSingleNativeIngress,
  canonicalNativeDest,
  CANONICAL_BUILDS,
  RUST_BUILD_SRC,
  RUST_DEST,
  withCanonicalBuilds,
} from './vercel_builds.mjs';

test('canonical builds declare one native Rust function and one static build', () => {
  assert.deepEqual(CANONICAL_BUILDS.map(build => [build.src, build.use]), [
    [RUST_BUILD_SRC, '@vercel/rust'],
    ['package.json', '@vercel/static-build'],
  ]);
  const document = withCanonicalBuilds({routes: [{src: '/api(?:/.*)?', dest: RUST_DEST}]});
  assert.equal(assertSingleNativeIngress(document), document);
});

test('both native entrypoint spellings normalize to the current canonical destination', () => {
  assert.equal(canonicalNativeDest('/api/native_roll.rs'), RUST_DEST);
  assert.equal(canonicalNativeDest('/api/native_api.rs'), RUST_DEST);
  // Non-native and non-string inputs pass through for the invariant checks.
  assert.equal(canonicalNativeDest('/api/retired.ingress'), '/api/retired.ingress');
  assert.equal(canonicalNativeDest(undefined), undefined);
  assert.equal(canonicalNativeDest(null), null);
  assert.equal(canonicalNativeDest(42), 42);
  assert.equal(RUST_DEST, '/api/native_roll.rs', 'canonical value stays at the deployed spelling');
  assert.equal(RUST_BUILD_SRC, 'api/native_roll.rs', 'build source is unchanged');
});

test('the future native_api destination still satisfies the single-ingress invariant', () => {
  const document = withCanonicalBuilds({routes: [
    {src: '^/api/v2/ping$', methods: ['GET'], dest: '/api/native_api.rs'},
    {src: '/api(?:/.*)?', dest: '/api/native_api.rs'},
  ]});
  assert.equal(assertSingleNativeIngress(document), document);
});

test('a second @vercel/rust build is rejected', () => {
  const document = withCanonicalBuilds({routes: []});
  document.builds.splice(1, 0, {src: 'api/native_issue.rs', use: '@vercel/rust'});
  assert.throws(
    () => assertSingleNativeIngress(document),
    /exactly one api\/native_roll\.rs @vercel\/rust build/,
  );
});

test('retired Issue and Python API destinations are rejected', () => {
  for (const dest of ['/api/native_issue.rs', '/api/index.py']) {
    const document = withCanonicalBuilds({
      routes: [{src: '^/api/v2/issues/[0-9]+$', methods: ['PATCH'], dest}],
    });
    assert.throws(() => assertSingleNativeIngress(document), /targets retired ingress/);
  }
});

test('a missing static build is rejected', () => {
  const document = withCanonicalBuilds({routes: []});
  document.builds = [{src: RUST_BUILD_SRC, use: '@vercel/rust'}];
  assert.throws(() => assertSingleNativeIngress(document), /exactly one package.json static build/);
});

test('the deployed manifest has one Rust build and routes all API traffic to it', () => {
  const document = JSON.parse(
    readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'),
  );
  assert.equal(assertSingleNativeIngress(document), document);
  const rustBuilds = document.builds.filter(build => build.use === '@vercel/rust');
  assert.equal(rustBuilds.length, 1);
  assert.equal(rustBuilds[0].src, RUST_BUILD_SRC);
  const apiRoutes = document.routes.filter(route => (route.src ?? '').startsWith('/api')
    || (route.src ?? '').startsWith('^/api/'));
  assert(apiRoutes.length > 0);
  for (const route of apiRoutes) {
    assert.equal(route.dest, RUST_DEST, `${route.src} must resolve to the single Rust function`);
  }
});
