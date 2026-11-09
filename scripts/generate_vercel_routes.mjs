#!/usr/bin/env node
/** Temporary cutover tool. Python declares its own legacy API routes;
 * Rust owns all unknown /api requests. Delete this once api/index.py is gone.
 * No new Python modules or database calls are introduced.
 */
import {execFileSync} from 'node:child_process';
import {readFileSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const PYTHON = '/api/index.py';
const RUST = '/api/native_roll.rs';
const NATIVE = new Set([RUST, '/api/native_issue.rs']);
const FALLBACK = '/api(?:/.*)?';
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];
const PARAM = /\{([^{}]+)\}/g;
const INVENTORY_EXCLUDED_OPERATIONS = new Set([
  'GET /api/v1/cron/release-sync',
]);

// Introspect the existing FastAPI application offline. This does not create
// another Python service, script, or long-lived process.
const METADATA_QUERY = [
  'import json',
  'from app.main import create_app',
  'from fastapi.routing import APIRoute',
  'app = create_app(serve_frontend=False, defer_router_imports=False)',
  'routes = []',
  'for r in app.routes:',
  '    if isinstance(r, APIRoute):',
  '        routes.append((r.path, r.methods, r.include_in_schema))',
  '    elif hasattr(r, "effective_route_contexts"):',
  '        routes.extend((context.path, context.methods, context.include_in_schema) for context in r.effective_route_contexts() if context.path == "/api/v1/cron/release-sync")',
  'print(json.dumps({"paths": app.openapi()["paths"], "registered": [',
  '{"path": p, "methods": sorted(methods), "visible": visible}',
  'for p, methods, visible in routes if p.startswith("/api/")]}))',
].join('\n');

export function pythonOperations(data) {
  const documented = new Set();
  for (const [path, operations] of Object.entries(data.paths)) {
    if (!path.startsWith('/api/')) continue;
    for (const method of Object.keys(operations)) {
      if (METHODS.includes(method.toUpperCase())) documented.add(method.toUpperCase() + ' ' + path);
    }
  }
  const registered = new Set();
  const visible = new Set();
  for (const r of data.registered) {
    if (!r.path.startsWith('/api/') || r.path === '/api/{path:path}') continue;
    for (const method of r.methods) {
      if (!METHODS.includes(method)) continue;
      const id = method + ' ' + r.path;
      registered.add(id);
      if (r.visible) visible.add(id);
    }
  }
  const missing = [...visible].filter(x => !documented.has(x));
  if (missing.length) throw new Error('Python OpenAPI lacks registered routes: ' + missing.slice(0, 8));
  return [...new Set([...registered, ...documented])].map(item => {
    const split = item.indexOf(' ');
    return [item.slice(0, split), item.slice(split + 1)];
  }).sort((a, b) => a[1].localeCompare(b[1]) || a[0].localeCompare(b[0]));
}

function escapeRegex(text) {
  return text.replace(/[\^$.*+?()[\]{}|\-]/g, '\\$&');
}
export function routeRegex(path) {
  let regex = '^';
  let cursor = 0;
  for (const match of path.matchAll(PARAM)) {
    regex += escapeRegex(path.slice(cursor, match.index));
    regex += match[1].endsWith(':path') ? '.+' : '[^/]+';
    cursor = match.index + match[0].length;
  }
  return regex + escapeRegex(path.slice(cursor)) + '$';
}
function alreadyNative(method, path, native) {
  const concrete = path.replace(PARAM, '1');
  return native.some(route =>
    (!route.methods || route.methods.includes(method)) && new RegExp(route.src).test(concrete));
}
export function generateVercel(config, operations) {
  const native = config.routes.filter(route => NATIVE.has(route.dest) && route.src !== FALLBACK);
  if (!native.length) throw new Error('Cannot generate without explicit native Rust routes');
  const byPath = new Map();
  for (const [method, path] of operations) {
    if (alreadyNative(method, path, native)) continue;
    if (!byPath.has(path)) byPath.set(path, new Set());
    byPath.get(path).add(method);
  }
  const exceptions = [...byPath].sort(([a], [b]) => a.localeCompare(b))
    .map(([path, methods]) => {
      methods.add('OPTIONS');
      return {src: routeRegex(path), methods: METHODS.filter(m => methods.has(m)), dest: PYTHON};
    });
  const rest = config.routes.filter(route => !native.includes(route) && route.dest !== PYTHON
    && !(route.src === FALLBACK && NATIVE.has(route.dest)));
  return {...config, routes: [...native, ...exceptions, {src: FALLBACK, dest: RUST}, ...rest]};
}

export function updateInventory(inventory, operations) {
  const full = inventory.full_surface;
  if (!full) throw new Error('Missing existing full_surface inventory');
  const prev = new Map([...full.v1_operations, ...full.unversioned_operations]
    .map(op => [op.method + ' ' + op.path, op]));
  const v1 = [];
  const unversioned = [];
  for (const [method, path] of operations) {
    const bucket = path.startsWith('/api/v1/') ? v1
      : path.startsWith('/api/v2/') ? null
      : path.startsWith('/api/') ? unversioned : null;
    if (!bucket) continue;
    const old = prev.get(method + ' ' + path);
    bucket.push({method, path, runtime: 'python-fastapi',
      status: old?.status || 'transitional',
      owning_issue: old?.owning_issue ?? null,
      consumers: old?.consumers || []});
  }
  return {...inventory, full_surface: {...full,
    catch_all: {src: FALLBACK, dest: RUST},
    v1_operations: v1, unversioned_operations: unversioned}};
}
export function normalizeOperationIds(operations) {
  return operations.map(operation => [operation.method, operation.path])
    .sort((a, b) => a[1].localeCompare(b[1]) || a[0].localeCompare(b[0]));
}
export function sameOperationIds(operations, expected) {
  return JSON.stringify(normalizeOperationIds(operations))
    === JSON.stringify(normalizeOperationIds(expected));
}
function inventoryOperations(operations) {
  return operations.filter(([method, path]) => !INVENTORY_EXCLUDED_OPERATIONS.has(`${method} ${path}`));
}
function inspect() {
  const env = {...process.env, ENVIRONMENT: 'production',
    SECRET_KEY: process.env.SECRET_KEY || 'synthetic-route-inspection-only',
    CORS_ORIGINS: process.env.CORS_ORIGINS || 'https://comic-pile.vercel.app'};
  const text = execFileSync(process.env.ROUTE_PYTHON || 'python',
    ['-c', METADATA_QUERY], {env, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024});
  return JSON.parse(text.trim().split('\n').at(-1));
}
function run() {
  const check = process.argv.includes('--check');
  const original = JSON.parse(readFileSync('vercel.json', 'utf8'));
  const inventory = JSON.parse(readFileSync('docs/api/v2-route-inventory.json', 'utf8'));
  const operations = pythonOperations(inspect());
  const nextVercel = JSON.stringify(generateVercel(original, operations), null, 2) + '\n';
  const nextInventory = updateInventory(inventory, inventoryOperations(operations));
  if (check) {
    const full = inventory.full_surface;
    if (readFileSync('vercel.json', 'utf8') !== nextVercel
        || !sameOperationIds(full.v1_operations, nextInventory.full_surface.v1_operations)
        || !sameOperationIds(full.unversioned_operations, nextInventory.full_surface.unversioned_operations)
        || full.catch_all.dest !== RUST) {
      throw new Error('Stale Vercel Python allowlist. Run node scripts/generate_vercel_routes.mjs');
    }
    console.log('Verified Rust-default ingress and ' + operations.length + ' Python route operations');
    return;
  }
  writeFileSync('vercel.json', nextVercel);
  writeFileSync('docs/api/v2-route-inventory.json', JSON.stringify(nextInventory, null, 2) + '\n');
  console.log('Generated Rust-default ingress from ' + operations.length + ' Python operations');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) run();
