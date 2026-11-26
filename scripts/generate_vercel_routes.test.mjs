import assert from 'node:assert/strict';
import {test} from 'node:test';
import {
  applyStaticCsp,
  fragmentVercelRoutes,
  generateVercel,
  routeRegex,
  STATIC_CSP,
} from './generate_vercel_routes.mjs';
import {CANONICAL_BUILDS} from './vercel_builds.mjs';

const NATIVE_API = '/api/native_api.rs';
const FALLBACK = '/api(?:/.*)?';

function baseConfig() {
  return {routes: [
    {src: '/api/v2/health', methods: ['GET'], dest: NATIVE_API},
    {src: '/api/v1/stale', methods: ['GET'], dest: '/api/retired.ingress'},
    {src: FALLBACK, dest: NATIVE_API},
    {src: '^/(?:openapi\\.json|docs|redoc|health)$', status: 404},
    {
      src: '/(.*)',
      dest: '/index.html',
      headers: {
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline';",
        'X-ComicPile-Frontend': 'vercel-static',
      },
    },
  ]};
}

function fragments() {
  return [
    {family: 'tags', defaults: {}, operations: [
      {method: 'GET', path: '/api/v1/tags/', dest: NATIVE_API, src: '^/api/v1/tags/$'},
      {method: 'POST', path: '/api/v1/tags/', dest: NATIVE_API, src: '^/api/v1/tags/$'},
    ]},
    {family: 'creators', defaults: {}, operations: [
      {method: 'GET', path: '/api/v1/creators', dest: NATIVE_API, src: '^/api/v1/creators$'},
    ]},
  ];
}

function resolve(config, method, path) {
  return config.routes.find(route => (!route.methods || route.methods.includes(method))
    && new RegExp(`^(?:${route.src})$`).test(path))?.dest;
}

test('static route CSP never permits script eval or inline scripts', () => {
  const old = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;";
  const staticRoutes = [
    {src: '/', dest: '/index.html', headers: {'Content-Security-Policy': old, 'X-ComicPile-Frontend': 'vercel-static'}},
    {src: '/(login|roll|queue)(\\.html)?', dest: '/$1.html', headers: {'Content-Security-Policy': old, 'X-Robots-Tag': 'noindex, nofollow'}},
    {src: '/(.*)', dest: '/index.html', headers: {'Content-Security-Policy': old}},
  ];
  const config = {routes: [...staticRoutes, {src: '/assets/.+', continue: true, headers: {'Cache-Control': 'immutable'}}]};
  const generated = applyStaticCsp(config);
  const headers = generated.routes.filter(route => route.headers?.['Content-Security-Policy'])
    .map(route => route.headers['Content-Security-Policy']);
  assert.equal(headers.length, 3);
  for (const csp of headers) {
    assert.equal(csp, STATIC_CSP);
    assert.equal(csp.includes('unsafe-eval'), false);
    assert.equal(/script-src[^;]*unsafe-inline/.test(csp), false);
    // Style inline is a separate, independently justified exception.
    assert.equal(/style-src[^;]*unsafe-inline/.test(csp), true);
  }
  assert.deepEqual(generated.routes[0].headers['X-ComicPile-Frontend'], 'vercel-static');
  assert.deepEqual(generated.routes[1].headers['X-Robots-Tag'], 'noindex, nofollow');
  assert.deepEqual(generated.routes[3].headers, {'Cache-Control': 'immutable'});
  assert.equal(applyStaticCsp(generated).routes[0].headers['Content-Security-Policy'], STATIC_CSP);
});

test('routeRegex is anchored and treats parameters as single path segments', () => {
  assert(new RegExp(routeRegex('/api/v1/threads/{id}')).test('/api/v1/threads/7'));
  assert(!new RegExp(routeRegex('/api/v1/threads/{id}')).test('/api/v1/threads/7/other'));
  assert(new RegExp(routeRegex('/api/{path:path}')).test('/api/a/b/c'));
});

test('fragment grouping is native-only, method-aware and deterministic', () => {
  const routes = fragmentVercelRoutes(fragments(), baseConfig().routes);
  assert.deepEqual(routes, [
    {src: '^/api/v1/creators$', methods: ['GET'], dest: NATIVE_API},
    {src: '^/api/v1/tags/$', methods: ['GET', 'POST'], dest: NATIVE_API},
  ]);
  assert.equal(routes.some(route => route.methods.includes('OPTIONS')), false);
  assert.deepEqual(fragmentVercelRoutes(fragments(), baseConfig().routes), routes);
});

test('fragment operations may inherit their native destination and source from the previous document', () => {
  const previous = [{src: '^/api/v1/tags/$', methods: ['GET'], dest: NATIVE_API}];
  const inherited = fragmentVercelRoutes([{family: 'tags', defaults: {}, operations: [
    {method: 'GET', path: '/api/v1/tags/'},
  ]}], previous);
  assert.deepEqual(inherited, [{src: '^/api/v1/tags/$', methods: ['GET'], dest: NATIVE_API}]);
});

test('non-native fragment destinations are rejected', () => {
  assert.throws(() => fragmentVercelRoutes([{family: 'retired', defaults: {}, operations: [
    {method: 'GET', path: '/api/v1/retired', dest: '/api/retired.ingress'},
  ]}], baseConfig().routes), /unknown destination/);
});

test('generation emits canonical builds, drops retired API ingress and keeps static routes', () => {
  const generated = generateVercel(baseConfig(), fragments());
  assert.deepEqual(generated.builds, CANONICAL_BUILDS);
  assert.equal(generated.routes.some(route => route.dest === '/api/retired.ingress'), false);
  assert.equal(generated.routes.some(route => route.src === '/api/v1/stale'), false);
  assert.deepEqual(generated.routes.find(route => route.src === FALLBACK), {src: FALLBACK, dest: NATIVE_API});
  assert.deepEqual(generated.routes.find(route => route.src === '^/(?:openapi\\.json|docs|redoc|health)$'),
    {src: '^/(?:openapi\\.json|docs|redoc|health)$', status: 404});
  assert.equal(generated.routes.at(-1).headers['X-ComicPile-Frontend'], 'vercel-static');
  assert.equal(generated.routes.at(-1).headers['Content-Security-Policy'], STATIC_CSP);
  // Every retired path still resolves to the Rust catch-all.
  assert.equal(resolve(generated, 'GET', '/api/v1/stale'), NATIVE_API);
  assert.equal(resolve(generated, 'POST', '/api/v1/tags/7'), NATIVE_API);
});

test('generation is byte-stable across a second regeneration', () => {
  const first = generateVercel(baseConfig(), fragments());
  const second = generateVercel(first, fragments());
  assert.deepEqual(second, first);
  assert.equal(JSON.stringify(second, null, 2), JSON.stringify(first, null, 2));
});

test('generation requires fragments and an explicit native baseline', () => {
  assert.throws(() => generateVercel(baseConfig(), []), /without route fragments/);
  assert.throws(() => generateVercel({routes: [{src: FALLBACK, dest: NATIVE_API}]}, fragments()),
    /without explicit native Rust routes/);
});
