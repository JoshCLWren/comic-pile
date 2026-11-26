#!/usr/bin/env node
/** Route-ingress generator. Every /api operation is owned by a route
 * fragment and routed to native Rust; the Python API and its ingress are
 * gone. This generator emits the canonical Vercel builds directly, so no
 * post-generation strip step is required.
 */
import {readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {assertSingleNativeIngress, withCanonicalBuilds} from './vercel_builds.mjs';
import {canonicalNativeDestination, slimNativeApiRoutes} from './vercel_slim_routes.mjs';

const RUST = '/api/native_api.rs';
const NATIVE = new Set([RUST]);
const FALLBACK = '/api(?:/.*)?';
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];

// CSP for the Vercel-served static HTML shell and per-page HTML routes.
// vercel.json is a bot-owned generated artifact and cannot be edited in an
// ordinary PR, so the browser-facing CSP is owned here and applied to every
// static route that declares a Content-Security-Policy header during
// generation. Script execution has no dynamic-eval requirement: the Vite build
// emits static module scripts only. Style inline is kept separate because
// Tailwind/Vite inject runtime CSS; it is not a script execution exception.
export const STATIC_CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: https:; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https://fonts.googleapis.com; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; frame-src 'none';";

/** Apply the canonical CSP to every static HTML route carrying one. */
export function applyStaticCsp(config) {
  return {
    ...config,
    routes: config.routes.map(route =>
      route.headers && Object.hasOwn(route.headers, 'Content-Security-Policy')
        ? {...route, headers: {...route.headers, 'Content-Security-Policy': STATIC_CSP}}
        : route,
    ),
  };
}
const PARAM = /\{([^{}]+)\}/g;

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
function isString(value) {
  return Object.prototype.toString.call(value) === '[object String]';
}
function isApiSource(src) {
  return src === FALLBACK || (isString(src)
    && (src.startsWith('/api/') || src.startsWith('^/api/')));
}
function compareCodeUnits(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}
function compareRoutes(left, right) {
  const src = compareCodeUnits(left.src, right.src);
  if (src !== 0) return src;
  const dest = compareCodeUnits(left.dest, right.dest);
  if (dest !== 0) return dest;
  return compareCodeUnits(left.methods.join(','), right.methods.join(','));
}
function findPreviousRoute(method, path, previousRoutes) {
  const concrete = path.replace(PARAM, '1');
  for (const route of previousRoutes) {
    if (!route.src) continue;
    if (route.methods && !route.methods.includes(method)) continue;
    try {
      const matched = new RegExp(`^(?:${route.src})$`).test(concrete);
      if (matched) return route;
    } catch {
      continue;
    }
  }
  return null;
}
/** Derive the explicit native rewrites owned by the route fragments. */
export function fragmentVercelRoutes(fragments, previousRoutes = []) {
  const grouped = new Map();
  for (const fragment of fragments) {
    const defaults = fragment.defaults || {};
    for (const rawOperation of fragment.operations) {
      const effective = {...defaults, ...rawOperation};
      const method = effective.method;
      const path = effective.path;
      let dest = effective.dest;
      let src = effective.src;
      const previous = findPreviousRoute(method, path, previousRoutes);
      if (!dest) {
        if (!previous || !previous.dest) {
          throw new Error(`${method} ${path} needs dest; previous vercel.json has no matching route`);
        }
        dest = previous.dest;
      }
      if (!src) {
        // The catch-all is never a fragment's own ingress src (slim vercel.json
        // relies on it instead of explicit native_api entries).
        src = (previous && previous.src !== FALLBACK && previous.src) || routeRegex(path);
      }
      if (!NATIVE.has(dest)) {
        throw new Error(`unknown destination ${dest} for ${method} ${path}`);
      }
      const key = `${src}|${dest}`;
      if (!grouped.has(key)) grouped.set(key, {src, dest, methods: new Set()});
      grouped.get(key).methods.add(method);
    }
  }
  return [...grouped.values()]
    .map(group => ({src: group.src, methods: METHODS.filter(m => group.methods.has(m)), dest: group.dest}))
    .sort(compareRoutes);
}
/** Generate the complete native-only Vercel document from route fragments. */
export function generateVercel(config, fragments) {
  if (!fragments || fragments.length === 0) {
    throw new Error('Cannot generate without route fragments');
  }
  const native = config.routes.filter(route => NATIVE.has(route.dest) && route.src !== FALLBACK);
  if (!native.length) throw new Error('Cannot generate without explicit native Rust routes');

  const fragmentRoutes = fragmentVercelRoutes(fragments, config.routes);
  const fragmentSrcs = new Set(fragmentRoutes.map(r => r.src));
  const baselineNatives = config.routes.filter(
    route => NATIVE.has(route.dest) && route.src !== FALLBACK && !fragmentSrcs.has(route.src),
  );
  // Only non-API routes survive from the previous document. Every API route
  // is either fragment-derived or the native catch-all below, so a retired
  // Python exception can never be carried forward.
  const rest = config.routes.filter(route => !native.includes(route) && !isApiSource(route.src));
  const fullRoutes = [
    ...baselineNatives,
    ...fragmentRoutes,
    {src: FALLBACK, dest: RUST},
    ...rest,
  ];
  // The deployed manifest must keep the single-function invariant (#5733):
  // one Rust compilation target and no retired API destination.
  return assertSingleNativeIngress(withCanonicalBuilds(applyStaticCsp({
    ...config,
    routes: slimNativeApiRoutes(fullRoutes, new Set(fragmentRoutes)),
  })));
}
export function loadFragmentFiles(directory = 'docs/api/route-fragments') {
  return readdirSync(directory)
    .filter(name => name.endsWith('.json') && name !== 'vercel-rewrites.json')
    .sort()
    .map(name => JSON.parse(readFileSync(`${directory}/${name}`, 'utf8')));
}

function run() {
  const check = process.argv.includes('--check');
  const committed = JSON.parse(readFileSync('vercel.json', 'utf8'));
  // A fragment-only PR cannot commit the bot-owned vercel.json until the
  // post-merge regeneration lands. Normalize the previous native entrypoint
  // at the I/O boundary before deriving the next artifact so generation stays
  // deterministic across the rename.
  const original = {
    ...committed,
    routes: committed.routes.map(route => {
      const dest = canonicalNativeDestination(route.dest);
      return dest === route.dest ? route : {...route, dest};
    }),
  };
  // Route fragments are the sole source of explicit /api rewrites; there is
  // no Python operation registry to sync into the inventory any longer.
  const fragments = loadFragmentFiles();
  const nextVercel = JSON.stringify(generateVercel(original, fragments), null, 2) + '\n';
  if (check) {
    const current = readFileSync('vercel.json', 'utf8');
    if (current !== nextVercel) {
      const before = JSON.parse(current);
      const after = JSON.parse(nextVercel);
      const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
      const differingKey = [...keys].find(key => JSON.stringify(before[key]) !== JSON.stringify(after[key]));
      throw new Error('Stale Vercel ingress. Run node scripts/generate_vercel_routes.mjs'
        + '; differing key=' + differingKey
        + '; actual=' + JSON.stringify(before[differingKey])
        + '; expected=' + JSON.stringify(after[differingKey]));
    }
    console.log('Verified native-only Vercel ingress with canonical builds');
    return;
  }
  writeFileSync('vercel.json', nextVercel);
  console.log('Generated native-only Vercel ingress with canonical builds');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) run();
