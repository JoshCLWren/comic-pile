import assert from 'node:assert/strict';
import {test} from 'node:test';
import {
  applyStaticCsp,
  fragmentVercelRoutes,
  generateVercel,
  normalizeOperationIds,
  pythonOperations,
  routeRegex,
  sameOperationIds,
  STATIC_CSP,
  updateInventory,
} from './generate_vercel_routes.mjs';

function metadata(withOrphan = true) {
  const paths = {
    '/api/v1/threads/{id}': {get: {}},
  };
  if (withOrphan) paths['/api/v1/orphan'] = {get: {}};

  const registered = [
    {path: '/api/v1/threads/{id}', methods: ['GET'], visible: true},
    {path: '/api/v1/cron/release-sync', methods: ['GET'], visible: false},
  ];
  if (withOrphan) registered.push({path: '/api/v1/orphan', methods: ['GET'], visible: true});
  registered.push({path: '/api/{path:path}', methods: ['GET'], visible: false});

  return {paths, registered};
}
const config = {routes: [
  {src: '/api/v2/health', methods: ['GET'], dest: '/api/native_api.rs'},
  {src: '/api(?:/.*)?', dest: '/api/index.py'},
  {src: '/(.*)', dest: '/index.html'},
]};
function destination(config, method, path) {
  return config.routes.find(route => (!route.methods || route.methods.includes(method))
    && new RegExp(route.src).test(path))?.dest;
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
test('raw OpenAPI plus hidden API routes, excluding the synthetic FastAPI 404', () => {
  const ops = pythonOperations(metadata());
  assert(ops.some(x => x[1] === '/api/v1/cron/release-sync'));
  assert(!ops.some(x => x[1] === '/api/{path:path}'));
});
test('full surface operation comparison ignores reordered operations', () => {
  const expected = [
    {method: 'GET', path: '/api/v1/threads/{id}'},
    {method: 'POST', path: '/api/v1/threads/{id}'},
  ];
  const reordered = [...expected].reverse();
  assert(sameOperationIds(reordered, expected));
  assert.deepEqual(normalizeOperationIds(reordered), [
    ['GET', '/api/v1/threads/{id}'],
    ['POST', '/api/v1/threads/{id}'],
  ]);
});
test('deleting Python routes automatically removes exceptions and returns Rust 404', () => {
  const before = generateVercel(config, pythonOperations(metadata()));
  const after = generateVercel(config, pythonOperations(metadata(false)));
  assert.equal(destination(before, 'GET', '/api/v1/orphan'), '/api/index.py');
  assert.equal(destination(after, 'GET', '/api/v1/orphan'), '/api/native_api.rs');
  assert.equal(destination(after, 'GET', '/api/v2/unknown'), '/api/native_api.rs');
  assert.equal(destination(after, 'GET', '/api/v1/cron/release-sync'), '/api/index.py');
  assert.equal(destination(after, 'GET', '/api/v2/health'), '/api/native_api.rs');
  assert.equal(destination(after, 'POST', '/api/v1/threads/7'), '/api/native_api.rs');
  assert.equal(destination(after, 'OPTIONS', '/api/v1/threads/7'), '/api/index.py');
});
test('generated config idempotence and anchored parameter matching', () => {
  const ops = pythonOperations(metadata(false));
  const generated = generateVercel(config, ops);
  assert.deepEqual(generateVercel(generated, ops), generated);
  assert(new RegExp(routeRegex('/api/v1/threads/{id}')).test('/api/v1/threads/7'));
  assert(!new RegExp(routeRegex('/api/v1/threads/{id}')).test('/api/v1/threads/7/other'));
});
test('an empty Python operation set leaves the fragment-owned inventory untouched', () => {
  const inventory = {full_surface: {v1_operations: [
    {method: 'GET', path: '/api/v1/tags/', consumers: ['client.ts'], status: 'transitional', owning_issue: 5},
  ], unversioned_operations: [], catch_all: {src: '/api(?:/.*)?', dest: '/api/native_api.rs'}}};
  assert.equal(updateInventory(inventory, []), inventory);
});
test('deleted Python routes leave the inventory, surviving caller metadata persists', () => {
  const inventory = {full_surface: {v1_operations: [
    {method: 'GET', path: '/api/v1/threads/{id}', consumers: ['client.ts'], status: 'transitional', owning_issue: 5},
    {method: 'GET', path: '/api/v1/orphan', consumers: [], status: 'transitional', owning_issue: null},
  ], unversioned_operations: [], catch_all: {src: '/api(?:/.*)?', dest: '/api/index.py'}}};
  const updated = updateInventory(inventory, pythonOperations(metadata(false)));
  assert.deepEqual(updated.full_surface.v1_operations.map(x => x.path),
    ['/api/v1/cron/release-sync', '/api/v1/threads/{id}']);
  assert.deepEqual(updated.full_surface.v1_operations.find(x => x.path.includes('threads')).consumers,
    ['client.ts']);
});
const familyConfig = {routes: [
  {src: '/api/v2/health', methods: ['GET'], dest: '/api/native_api.rs'},
  {src: '/api(?:/.*)?', dest: '/api/native_api.rs'},
  {src: '^/(?:openapi\\.json|docs|redoc|health)$', status: 404},
  {src: '/(.*)', dest: '/index.html'},
]};
function familyFragments() {
  return [
    {family: 'tags', defaults: {}, operations: [
      {bucket: 'v1_operations', method: 'GET', path: '/api/v1/tags/', dest: '/api/index.py', src: '^/api/v1/tags/$'},
      {bucket: 'v1_operations', method: 'POST', path: '/api/v1/tags/', dest: '/api/index.py', src: '^/api/v1/tags/$'},
    ]},
    {family: 'creators', defaults: {}, operations: [
      {bucket: 'v1_operations', method: 'GET', path: '/api/v1/creators', dest: '/api/native_api.rs', src: '^/api/v1/creators$'},
    ]},
  ];
}
test('new family fragment merges without touching another family fragment', () => {
  const fragments = familyFragments();
  const tagsOnly = [fragments[0]];
  const full = fragmentVercelRoutes(fragments, familyConfig.routes);
  const tagsOnlyRoutes = fragmentVercelRoutes(tagsOnly, familyConfig.routes);
  // Tags-only derivation contains only the tags Python group.
  assert.deepEqual(tagsOnlyRoutes, [
    {src: '^/api/v1/tags/$', methods: ['GET', 'POST', 'OPTIONS'], dest: '/api/index.py'},
  ]);
  // Full derivation adds the creators native route before the Python group.
  assert.equal(full[0].src, '^/api/v1/creators$');
  assert.equal(full[0].dest, '/api/native_api.rs');
  assert.deepEqual(full[1], tagsOnlyRoutes[0]);
  // Flipping one family's dest leaves the other family's route unchanged.
  const flipped = [
    {...fragments[0], operations: fragments[0].operations.map(op => ({...op, dest: '/api/native_api.rs'}))},
    fragments[1],
  ];
  const flippedRoutes = fragmentVercelRoutes(flipped, familyConfig.routes);
  assert(flippedRoutes.some(r => r.src === '^/api/v1/tags/$' && r.dest === '/api/native_api.rs'));
  assert(flippedRoutes.some(r => r.src === '^/api/v1/creators$' && r.dest === '/api/native_api.rs'));
});
test('fragment generation is idempotent and native-before-Python ordered', () => {
  const fragments = familyFragments();
  const first = fragmentVercelRoutes(fragments, familyConfig.routes);
  const second = fragmentVercelRoutes(fragments, familyConfig.routes);
  assert.deepEqual(first, second);
  const nativeFirst = first.findIndex(r => r.dest === '/api/index.py');
  assert(first.slice(0, nativeFirst).every(r => r.dest !== '/api/index.py'));
  assert(first.slice(nativeFirst).every(r => r.dest === '/api/index.py'));
  const generated = generateVercel(familyConfig, pythonOperations(metadata()), fragments);
  assert.deepEqual(generateVercel(generated, pythonOperations(metadata()), fragments), generated);
});
test('hidden cron exception survives fragment derivation', () => {
  const fragments = familyFragments();
  const generated = generateVercel(familyConfig, pythonOperations(metadata()), fragments);
  function destFor(routeConfig, method, path) {
    return routeConfig.routes.find(route => (!route.methods || route.methods.includes(method))
      && new RegExp(route.src).test(path))?.dest;
  }
  assert.equal(destFor(generated, 'GET', '/api/v1/cron/release-sync'), '/api/index.py');
});
