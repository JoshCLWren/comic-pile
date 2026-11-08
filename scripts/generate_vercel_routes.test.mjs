import assert from 'node:assert/strict';
import {test} from 'node:test';
import {generateVercel, pythonOperations, routeRegex, updateInventory} from './generate_vercel_routes.mjs';

function metadata(withOrphan = true) {
  return {
    paths: {
      '/api/v1/threads/{id}': {get: {}},
      ...(withOrphan ? {'/api/v1/orphan': {get: {}}} : {}),
    },
    registered: [
      {path: '/api/v1/threads/{id}', methods: ['GET'], visible: true},
      {path: '/api/v1/cron/release-sync', methods: ['GET'], visible: false},
      ...(withOrphan ? [{path: '/api/v1/orphan', methods: ['GET'], visible: true}] : []),
      {path: '/api/{path:path}', methods: ['GET'], visible: false},
    ],
  };
}
const config = {routes: [
  {src: '/api/v2/health', methods: ['GET'], dest: '/api/native_roll.rs'},
  {src: '/api(?:/.*)?', dest: '/api/index.py'},
  {src: '/(.*)', dest: '/index.html'},
]};
function destination(config, method, path) {
  return config.routes.find(route => (!route.methods || route.methods.includes(method))
    && new RegExp(route.src).test(path))?.dest;
}
test('raw OpenAPI plus hidden API routes, excluding the synthetic FastAPI 404', () => {
  const ops = pythonOperations(metadata());
  assert(ops.some(x => x[1] === '/api/v1/cron/release-sync'));
  assert(!ops.some(x => x[1] === '/api/{path:path}'));
});
test('deleting Python routes automatically removes exceptions and returns Rust 404', () => {
  const before = generateVercel(config, pythonOperations(metadata()));
  const after = generateVercel(config, pythonOperations(metadata(false)));
  assert.equal(destination(before, 'GET', '/api/v1/orphan'), '/api/index.py');
  assert.equal(destination(after, 'GET', '/api/v1/orphan'), '/api/native_roll.rs');
  assert.equal(destination(after, 'GET', '/api/v2/unknown'), '/api/native_roll.rs');
  assert.equal(destination(after, 'GET', '/api/v1/cron/release-sync'), '/api/index.py');
  assert.equal(destination(after, 'GET', '/api/v2/health'), '/api/native_roll.rs');
  assert.equal(destination(after, 'POST', '/api/v1/threads/7'), '/api/native_roll.rs');
  assert.equal(destination(after, 'OPTIONS', '/api/v1/threads/7'), '/api/index.py');
});
test('generated config idempotence and anchored parameter matching', () => {
  const ops = pythonOperations(metadata(false));
  const generated = generateVercel(config, ops);
  assert.deepEqual(generateVercel(generated, ops), generated);
  assert(new RegExp(routeRegex('/api/v1/threads/{id}')).test('/api/v1/threads/7'));
  assert(!new RegExp(routeRegex('/api/v1/threads/{id}')).test('/api/v1/threads/7/other'));
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
