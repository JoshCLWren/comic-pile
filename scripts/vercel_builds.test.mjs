import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {
  assertSingleNativeIngress,
  CANONICAL_BUILDS,
  RUST_BUILD_SRC,
  RUST_DEST,
  withCanonicalBuilds,
} from './vercel_builds.mjs';
import {canonicalNativeBuild, canonicalNativeDestination} from './vercel_slim_routes.mjs';

test('canonical builds declare one native Rust function and one static build', () => {
  assert.deepEqual(CANONICAL_BUILDS.map(build => [build.src, build.use]), [
    [RUST_BUILD_SRC, '@vercel/rust'],
    ['package.json', '@vercel/static-build'],
  ]);
  const document = withCanonicalBuilds({routes: [{src: '/api(?:/.*)?', dest: RUST_DEST}]});
  assert.equal(assertSingleNativeIngress(document), document);
});

test('a second @vercel/rust build is rejected', () => {
  const document = withCanonicalBuilds({routes: []});
  document.builds.splice(1, 0, {src: 'api/native_issue.rs', use: '@vercel/rust'});
  assert.throws(
    () => assertSingleNativeIngress(document),
    /exactly one api\/native_api\.rs @vercel\/rust build/,
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
  // The committed vercel.json is bot-owned and is regenerated after a rename
  // merges. Decode any earlier native entrypoint at this test's I/O boundary.
  const committed = JSON.parse(
    readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'),
  );
  const document = {
    ...committed,
    builds: committed.builds.map(canonicalNativeBuild),
    routes: committed.routes.map(route => {
      const dest = canonicalNativeDestination(route.dest);
      return dest === route.dest ? route : {...route, dest};
    }),
  };
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
