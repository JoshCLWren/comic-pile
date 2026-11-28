#!/usr/bin/env node
/**
 * Final legacy-route guard for the API cutover (#5958).
 *
 * The live route census guards new first-party callers and inner-router
 * registrations. This guard covers the remaining deployment surfaces it does
 * not inspect: the separate Vercel ingress router, route-fragment operations,
 * fragment-declared crons and retired rewrite sources. A legacy METHOD/path
 * may exist only while it is still owned by an open migration in the generated
 * retirement allowlist (`GET /api/metrics` is the documented infrastructure
 * exemption). When the last owner lands, the allowlist empties and this guard
 * rejects every registered v1/unversioned application endpoint automatically.
 *
 * Usage:
 *   node scripts/check_final_legacy_route_guard.mjs [--root DIR]
 */
import {readFileSync, readdirSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_ROOT = path.resolve(HERE, '..');
export const INNER_ROUTER = 'native/roll-service/src/lib.rs';
export const INGRESS_ROUTER = 'api/native_roll.rs';
export const FRAGMENT_DIR = 'docs/api/route-fragments';
export const ALLOWLIST = 'docs/api/v1-retirement-allowlist.json';
export const INFRA_EXEMPTION = 'GET /api/metrics';
const VERBS = ['get', 'post', 'put', 'patch', 'delete'];

/** True for v1 and bare-domain application paths; v2 and /api/metrics are not legacy. */
export function isLegacyPath(pathname) {
  if (typeof pathname !== 'string') return false;
  if (pathname === '/api/metrics') return false; // documented operational exemption
  return pathname.startsWith('/api/v1/')
    || /^\/api\/[^v/]/.test(pathname)
    || /^\/api\/v[^12]/.test(pathname);
}

export const routeKey = (method, pathname) => `${method} ${pathname}`;

/** Extract registered METHOD/path pairs from an axum router's source text. */
export function parseRegisteredRoutes(source) {
  // Unit tests contain fixture routes and intentional negative probes; they
  // are not production registrations. Match the test module declaration rather
  // than a bare attribute: both routers have an early #[cfg(test)] task-local.
  const testModule = /\n\s*#\[cfg\(test\)\]\s*\n\s*mod tests\b/.exec(source);
  let production = testModule ? source.slice(0, testModule.index) : source;
  const routerDecl = /\bfn (?:router|app)\s*\(/.exec(production);
  if (routerDecl) production = production.slice(routerDecl.index);
  const routes = [];
  const routePattern = /\.route\(\s*"([^"]+)"\s*,/g;
  let match;
  while ((match = routePattern.exec(production)) !== null) {
    const next = production.indexOf('.route(', routePattern.lastIndex);
    const segment = production.slice(routePattern.lastIndex, next === -1 ? production.length : next);
    const methods = VERBS.filter(verb => new RegExp(`\\b${verb}\\s*\\(`).test(segment));
    for (const method of methods) routes.push({method: method.toUpperCase(), path: match[1]});
  }
  return routes;
}

function readJson(root, relative) {
  return JSON.parse(readFileSync(path.join(root, relative), 'utf8'));
}

/** The curated set of legacy routes still permitted while their owners are open. */
export function allowedLegacyKeys(root) {
  const allowlist = readJson(root, ALLOWLIST);
  const entries = Array.isArray(allowlist.entries) ? allowlist.entries : [];
  return new Set([
    INFRA_EXEMPTION,
    ...entries
      .filter(entry => entry && (entry.version === 'v1' || entry.version === 'unversioned'))
      .map(entry => routeKey(entry.method, entry.path)),
  ]);
}

/**
 * Validate router, ingress and fragment surfaces.
 *
 * @param {string} root Repository or fixture root.
 * @returns {string[]} Sorted, human-readable guard violations.
 */
export function collectViolations(root = DEFAULT_ROOT) {
  const allowed = allowedLegacyKeys(root);
  const violations = [];

  const routers = [
    [INNER_ROUTER, parseRegisteredRoutes(readFileSync(path.join(root, INNER_ROUTER), 'utf8'))],
    [INGRESS_ROUTER, parseRegisteredRoutes(readFileSync(path.join(root, INGRESS_ROUTER), 'utf8'))],
  ];
  const registered = new Map();
  for (const [label, routes] of routers) {
    const keys = new Set();
    for (const {method, path: pathname} of routes) {
      if (!isLegacyPath(pathname)) continue;
      const key = routeKey(method, pathname);
      keys.add(key);
      if (!allowed.has(key)) {
        violations.push(`${label}: registered legacy application endpoint ${key}`);
      }
    }
    registered.set(label, keys);
  }
  // Inner/ingress parity: a legacy alias must be reachable on both surfaces
  // while it is still owned, otherwise one deployment answers 404 and the
  // other dispatches to Rust with a different contract.
  for (const key of allowed) {
    if (key === INFRA_EXEMPTION) continue;
    for (const [label, keys] of registered) {
      if (!keys.has(key)) violations.push(`${label}: allowlisted legacy route ${key} is not registered`);
    }
  }

  const fragmentDir = path.join(root, FRAGMENT_DIR);
  const retiredSources = [];
  for (const name of readdirSync(fragmentDir).sort()) {
    if (!name.endsWith('.json') || name === 'vercel-rewrites.json') continue;
    const fragment = readJson(root, path.join(FRAGMENT_DIR, name));
    for (const operation of Array.isArray(fragment.operations) ? fragment.operations : []) {
      if (!isLegacyPath(operation.path)) continue;
      const key = routeKey(operation.method, operation.path);
      if (!allowed.has(key)) {
        violations.push(`${FRAGMENT_DIR}/${name}: legacy fragment operation ${key}`);
      }
    }
    const generation = fragment.vercel_generation || {};
    for (const cron of Array.isArray(generation.crons) ? generation.crons : []) {
      if (isLegacyPath(cron.path)) {
        violations.push(`${FRAGMENT_DIR}/${name}: legacy cron target ${cron.path}`);
      }
    }
    for (const src of Array.isArray(generation.retired_rewrite_srcs) ? generation.retired_rewrite_srcs : []) {
      retiredSources.push({fragment: name, src});
    }
  }
  // A retired rewrite source must no longer be reachable on either router or
  // declared by a live fragment operation.
  const allRouterPaths = routers.flatMap(([, routes]) => routes.map(route => route.path));
  for (const {fragment, src} of retiredSources) {
    let regex;
    try {
      regex = new RegExp(`^(?:${src})$`);
    } catch {
      violations.push(`${FRAGMENT_DIR}/${fragment}: invalid retired rewrite src ${src}`);
      continue;
    }
    if (allRouterPaths.some(pathname => regex.test(pathname.replace(/\{[^}]+\}/g, '1')))) {
      violations.push(`${FRAGMENT_DIR}/${fragment}: retired rewrite src ${src} is still registered`);
    }
  }
  return violations.sort();
}

export function main(argv = process.argv.slice(2)) {
  let root = DEFAULT_ROOT;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--root') root = path.resolve(argv[++index]);
    else throw new Error(`unknown argument: ${argv[index]}`);
  }
  const violations = collectViolations(root);
  if (violations.length) {
    console.error('final legacy route guard failed:');
    for (const violation of violations) console.error(`  - ${violation}`);
    return 1;
  }
  console.log('Verified final legacy route guard: no unowned v1/unversioned endpoints');
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
