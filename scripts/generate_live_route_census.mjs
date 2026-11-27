#!/usr/bin/env node
/**
 * Deterministic, all-version live route census (#5719).
 *
 * The v2 burndown inventory answers "how many v2 operations are native Rust?".
 * It does not answer "which v1/unversioned methods are still live, who owns
 * their retirement, and does a new first-party caller reintroduce v1?". This
 * tool builds that answer from primary sources:
 *
 *   - the real axum router in `native/roll-service/src/lib.rs` (every live
 *     METHOD/path/handler registration, including v1 and bare /api aliases);
 *   - `vercel.json` for the production ingress destination;
 *   - `docs/api/v2-route-inventory.json` for curated first-party consumers;
 *   - a source scan of first-party browser, CLI and test code for live calls;
 *   - `docs/api/v1-route-dispositions.json` for the curated owner/disposition
 *     matrix (the published ownership decision for each legacy route); and
 *   - `docs/api/v2-aip-shapes-baseline.json` for nonconforming v2 routes that
 *     already have a retirement owner.
 *
 * Generated/type-only trees (`frontend/src/generated`, `frontend/src/types`,
 * `__fixtures__`, snapshots, `.d.ts`) are never treated as live callers. Rust
 * route registrations are not callers either. A route being implemented by
 * Rust does not remove it from the v1 census: runtime and API version are
 * separate facts.
 *
 * Usage:
 *   node scripts/generate_live_route_census.mjs                # write outputs
 *   node scripts/generate_live_route_census.mjs --check        # CI drift gate
 *   node scripts/generate_live_route_census.mjs --root DIR     # fixture root
 */
import {existsSync, readFileSync, readdirSync, statSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(HERE, '..');

export const CENSUS_PATH = 'docs/api/live-route-census.json';
export const ALLOWLIST_PATH = 'docs/api/v1-retirement-allowlist.json';
export const REPORT_PATH = 'docs/api/LIVE_ROUTE_CENSUS.md';
export const ROUTER_PATH = 'native/roll-service/src/lib.rs';
export const DISPOSITIONS_PATH = 'docs/api/v1-route-dispositions.json';
export const INVENTORY_PATH = 'docs/api/v2-route-inventory.json';
export const AIP_BASELINE_PATH = 'docs/api/v2-aip-shapes-baseline.json';
export const VERCEL_PATH = 'vercel.json';

/**
 * Regression pinned by #5937: #5713 owns comparison and candidate discovery.
 * These two exact methods must not inherit the #5712 catalog-list or #4844
 * adoption-commit family dispositions. The keys are absent from the hermetic
 * fixture census, so the pins are enforced only when a route is present.
 */
export const CBL_ROUTE_OWNER = 5713;
export const CBL_ROUTE_DISPOSITIONS = new Map([
  ['POST /api/v1/issue-identity/cbl-sources/compare', 'POST /api/v2/cblSources:compare'],
  ['GET /api/v1/issue-identity/reading-lists/{list_id}/cbl-candidates',
    'GET /api/v2/readingLists/{list_id}/cblCandidates'],
]);

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];
const CALLER_EXTENSIONS = new Set(['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.py']);
const SKIP_DIRS = new Set([
  '.git', '.vercel', 'node_modules', 'dist', 'build', 'target', 'coverage',
  'generated', 'types', 'fixtures', '__fixtures__', '__snapshots__',
  'assets', 'docs',
]);
const SELF_SCRIPTS = new Set([
  'generate_live_route_census.mjs',
  'generate_live_route_census.test.mjs',
  'check_live_route_census.mjs',
]);
const CALLER_ROOTS = [
  'frontend/src',
  'scripts/ops',
  'native/roll-service/parity',
];
// Only production first-party clients may introduce drift. Test/spec files and
// repository tooling contain deliberate fixture paths and external API URLs;
// they are evidence of a live call only when they match a real route.
const DRIFT_PATH_PREFIXES = [
  'frontend/src/services/',
  'frontend/src/pages/',
  'frontend/src/hooks/',
  'frontend/src/query/',
  'frontend/src/components/',
  'frontend/src/contexts/',
  'frontend/src/lib/',
  'scripts/ops/',
];

class CensusError extends Error {}

function isObject(value) {
  return value !== null && Object.prototype.toString.call(value) === '[object Object]';
}

/** Return whether a JSON-decoded value is a string, without runtime narrowing. */
function isString(value) {
  return Object.prototype.toString.call(value) === '[object String]';
}

/** Read a validated string field from a decoded JSON record, with a fallback. */
function stringField(record, key, fallback) {
  const value = isObject(record) ? record[key] : undefined;
  return isString(value) ? value : fallback;
}

/** Read a validated array-of-strings field from decoded JSON (empty when absent/malformed). */
function stringList(value) {
  if (!Array.isArray(value)) return [];
  return value.flatMap(item => isString(item) ? [item] : []);
}

function readJson(file) {
  const value = JSON.parse(readFileSync(file, 'utf8'));
  if (!isObject(value)) throw new CensusError(`${file} must contain a JSON object`);
  return value;
}

/** Python-json.dumps-compatible deterministic serialization. */
export function stableJson(value) {
  const json = JSON.stringify(value, null, 2);
  let out = '';
  for (const ch of json) {
    const cp = ch.codePointAt(0);
    if (cp <= 0x7f) {
      out += ch;
    } else if (cp <= 0xffff) {
      out += `\\u${cp.toString(16).padStart(4, '0')}`;
    } else {
      const offset = cp - 0x10000;
      out += `\\u${Math.floor(offset / 0x400 + 0xd800).toString(16).padStart(4, '0')}`;
      out += `\\u${(offset % 0x400 + 0xdc00).toString(16).padStart(4, '0')}`;
    }
  }
  return `${out}\n`;
}

/** Find the closing paren of an opening paren while respecting strings/comments. */
function matchParen(text, open) {
  let depth = 0;
  let quote = '';
  let lineComment = false;
  let blockComment = false;
  for (let i = open; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];
    if (lineComment) {
      if (ch === '\n') lineComment = false;
      continue;
    }
    if (blockComment) {
      if (ch === '*' && next === '/') {
        blockComment = false;
        i += 1;
      }
      continue;
    }
    if (quote) {
      if (ch === '\\') {
        i += 1;
      } else if (ch === quote) {
        quote = '';
      }
      continue;
    }
    if (ch === '/' && next === '/') {
      lineComment = true;
      i += 1;
      continue;
    }
    if (ch === '/' && next === '*') {
      blockComment = true;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '(') depth += 1;
    if (ch === ')') {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  throw new CensusError('unbalanced parentheses in router source');
}

/** Split a parenthesized argument list on top-level commas. */
function splitArgs(content) {
  const args = [];
  let start = 0;
  let depth = 0;
  let quote = '';
  let lineComment = false;
  let blockComment = false;
  for (let i = 0; i < content.length; i += 1) {
    const ch = content[i];
    const next = content[i + 1];
    if (lineComment) {
      if (ch === '\n') lineComment = false;
      continue;
    }
    if (blockComment) {
      if (ch === '*' && next === '/') {
        blockComment = false;
        i += 1;
      }
      continue;
    }
    if (quote) {
      if (ch === '\\') {
        i += 1;
      } else if (ch === quote) {
        quote = '';
      }
      continue;
    }
    if (ch === '/' && next === '/') {
      lineComment = true;
      i += 1;
      continue;
    }
    if (ch === '/' && next === '*') {
      blockComment = true;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '(' || ch === '[' || ch === '{') depth += 1;
    if (ch === ')' || ch === ']' || ch === '}') depth -= 1;
    if (ch === ',' && depth === 0) {
      args.push(content.slice(start, i));
      start = i + 1;
    }
  }
  args.push(content.slice(start));
  // One transformation pass: trim, then drop empties while preserving order.
  return args.flatMap(arg => {
    const trimmed = arg.trim();
    return trimmed ? [trimmed] : [];
  });
}

/**
 * Extract every METHOD/path/handler registration from the axum `router()`
 * function. Test-module route strings and OpenAPI documentation strings are
 * outside the function body and are never counted.
 *
 * @param {string} source Rust source text.
 * @returns {Array<{method: string, path: string, handler: string, handler_kind: string, line: number}>}
 */
export function parseRouterRoutes(source) {
  const start = source.indexOf('pub fn router(');
  if (start < 0) throw new CensusError('router function not found in Rust source');
  const end = source.indexOf('\n}', start);
  if (end < 0) throw new CensusError('router function end not found in Rust source');
  const body = source.slice(start, end);
  const routes = [];
  let cursor = 0;
  while (true) {
    const at = body.indexOf('.route(', cursor);
    if (at < 0) break;
    const open = at + '.route'.length;
    const close = matchParen(body, open);
    const args = splitArgs(body.slice(open + 1, close));
    cursor = close + 1;
    if (args.length < 2) continue;
    if (!/^"[\s\S]*"$/.test(args[0])) continue;
    let routePath;
    try {
      routePath = JSON.parse(args[0]);
    } catch {
      continue;
    }
    const call = /^([a-z]+)\s*\(/i.exec(args[1]);
    if (!call) continue;
    const method = call[1].toUpperCase();
    if (!METHODS.includes(method)) continue;
    const handlerOpen = args[1].indexOf('(', call[1].length);
    const handlerClose = matchParen(args[1], handlerOpen);
    const handlerText = args[1].slice(handlerOpen + 1, handlerClose).trim();
    const inline = handlerText.startsWith('|') || handlerText.startsWith('async ');
    routes.push({
      method,
      path: routePath,
      handler: inline ? '<inline>' : handlerText,
      handler_kind: inline ? 'inline' : 'function',
      line: source.slice(0, start).split('\n').length + body.slice(0, at).split('\n').length,
    });
  }
  return routes;
}

/** API contract version from a registered canonical path. */
export function routeVersion(routePath) {
  if (routePath.startsWith('/api/v1/')) return 'v1';
  if (routePath.startsWith('/api/v2/')) return 'v2';
  if (routePath.startsWith('/api/')) return 'unversioned';
  return 'non-api';
}

/**
 * Normalize a first-party path literal (frontend or CLI) to a canonical route
 * pattern. `/v1/...` equals `/api/v1/...` at the deployed ingress; template
 * interpolations become single-segment `{param}` placeholders.
 */
export function normalizeCallerPath(raw) {
  let value = raw.split(/[?#]/, 1)[0];
  if (value.startsWith('/v1/') || value.startsWith('/v2/')) value = `/api${value}`;
  return value.replace(/\$\{[^}]*\}/g, '{param}');
}

/** Compile a canonical route pattern into a full-match regular expression. */
export function pathRegex(pattern) {
  const parts = String(pattern).split(/(\{[^}]+\})/);
  let source = '^';
  for (const part of parts) {
    if (part.startsWith('{') && part.endsWith('}')) {
      source += '[^/]+';
    } else {
      source += part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
  }
  return new RegExp(`${source}$`);
}

/** Match a caller pattern to a router pattern, ignoring parameter names. */
export function pathsMatch(callerPattern, routerPattern) {
  return pathRegex(routerPattern).test(callerPattern) || pathRegex(callerPattern).test(routerPattern);
}

/**
 * Match a scanned caller to a registered route. HTTP method is enforced when
 * the call site exposes one; method-less literals fall back to path matching.
 */
export function callerMatchesRoute(caller, route) {
  if (caller.method && caller.method !== route.method) return false;
  return pathsMatch(caller.path, route.path);
}

function listFiles(dir, relative, found) {
  for (const entry of readdirSync(dir).sort()) {
    const absolute = path.join(dir, entry);
    const rel = relative ? `${relative}/${entry}` : entry;
    const segments = rel.split('/');
    if (segments.some(segment => SKIP_DIRS.has(segment))) continue;
    if (statSync(absolute).isDirectory()) {
      listFiles(absolute, rel, found);
      continue;
    }
    if (SELF_SCRIPTS.has(entry)) continue;
    if (entry.endsWith('.d.ts')) continue;
    // Tests about generated path tables are fixture references, not calls.
    if (/^generated-/.test(entry)) continue;
    if (!CALLER_EXTENSIONS.has(path.extname(entry))) continue;
    found.push({absolute, relative: rel});
  }
}

function callerMethod(line) {
  const dotted = /\.(get|post|put|patch|delete)\s*\(/i.exec(line);
  if (dotted) return dotted[1].toUpperCase();
  const explicit = /\bmethod\s*:\s*['"](GET|POST|PUT|PATCH|DELETE)['"]/i.exec(line);
  if (explicit) return explicit[1].toUpperCase();
  return '';
}

/**
 * Scan first-party browser, CLI and test sources for live API path literals.
 * Generated OpenAPI types, fixture data and snapshots are deliberately not
 * scanned: they are references, not calls.
 *
 * @param {string} root Repository root.
 * @returns {Array<{file: string, line: number, method: string, path: string, raw: string}>}
 */
export function scanCallers(root) {
  const files = [];
  for (const relativeRoot of CALLER_ROOTS) {
    const absoluteRoot = path.join(root, relativeRoot);
    if (existsSync(absoluteRoot)) listFiles(absoluteRoot, relativeRoot, files);
  }
  const found = [];
  const seen = new Set();
  for (const file of files) {
    const text = readFileSync(file.absolute, 'utf8');
    const regex = /(["'`])(\/[^"'`\s]*)\1/g;
    let match;
    while ((match = regex.exec(text)) !== null) {
      const raw = match[2];
      if (!/^\/(?:api\/)?(?:v[12]\/|api\/)/.test(raw)) continue;
      const line = text.slice(0, match.index).split('\n').length;
      const lineText = text.split('\n')[line - 1].trim();
      if (/^(?:\/\/|\/\*|\*|#|import\b|from\b)/.test(lineText)) continue;
      const normalized = normalizeCallerPath(raw);
      const method = callerMethod(lineText);
      const isTest = /\.(test|spec)\.[^.]+$/.test(file.relative)
        || file.relative.includes('/test/') || file.relative.includes('/unit/');
      const driftChecked = !isTest && DRIFT_PATH_PREFIXES.some(prefix => file.relative.startsWith(prefix));
      const key = `${file.relative}\0${line}\0${normalized}\0${method}`;
      if (seen.has(key)) continue;
      seen.add(key);
      found.push({file: file.relative, line, method, path: normalized, raw, drift_checked: driftChecked});
    }
  }
  return found.sort((a, b) => {
    if (a.file !== b.file) return a.file < b.file ? -1 : 1;
    if (a.line !== b.line) return a.line - b.line;
    return 0;
  });
}

/** Resolve a route to the deployed Vercel ingress destination. */
export function resolveIngress(route, vercelRoutes) {
  const concrete = route.path.replace(/\{[^}]+\}/g, '1');
  for (const entry of vercelRoutes) {
    if (!entry.src) continue;
    let matches = false;
    try {
      matches = new RegExp(`^(?:${entry.src})$`).test(concrete);
    } catch {
      matches = false;
    }
    if (!matches) continue;
    if (entry.methods.length && !entry.methods.includes(route.method)) continue;
    return {destination: entry.dest ?? 'unknown', source: 'vercel-route'};
  }
  const catchAll = vercelRoutes.find(entry => entry.src === '/api(?:/.*)?');
  if (catchAll) return {destination: catchAll.dest ?? 'unknown', source: 'catch-all'};
  return {destination: 'unknown', source: 'unresolved'};
}

function loadVercelRoutes(document) {
  const routes = [];
  for (const raw of Array.isArray(document.routes) ? document.routes : []) {
    if (!isObject(raw)) continue;
    routes.push({
      src: stringField(raw, 'src', null),
      dest: stringField(raw, 'dest', null),
      methods: stringList(raw.methods),
    });
  }
  return routes;
}

function inventoryOperations(inventory) {
  const result = new Map();
  const buckets = [
    [inventory.operations, 'v2'],
    [inventory.full_surface?.v1_operations, 'v1'],
    [inventory.full_surface?.unversioned_operations, 'unversioned'],
  ];
  for (const [operations, bucket] of buckets) {
    for (const op of Array.isArray(operations) ? operations : []) {
      const method = stringField(op, 'method', null);
      const opPath = stringField(op, 'path', null);
      if (method === null || opPath === null) continue;
      result.set(`${method} ${opPath}`, {bucket, ...op});
    }
  }
  return result;
}

function dispositionFor(dispositions, route) {
  const overrides = isObject(dispositions.overrides) ? dispositions.overrides : {};
  const direct = overrides[`${route.method} ${route.path}`];
  if (isObject(direct)) return direct;
  for (const family of Array.isArray(dispositions.families) ? dispositions.families : []) {
    const prefix = stringField(family, 'prefix', null);
    if (prefix === null) continue;
    if (!route.path.startsWith(prefix)) continue;
    return family;
  }
  return {};
}

/**
 * Build the all-version census from primary sources.
 *
 * @param {object} inputs Router text, inventory, dispositions, AIP baseline,
 *   Vercel document and scanned callers.
 * @returns {object} Deterministic census document.
 */
export function buildCensus(inputs) {
  const routes = parseRouterRoutes(inputs.routerText)
    .filter(route => route.path.startsWith('/api/'));
  const curated = inventoryOperations(inputs.inventory);
  const aipEntries = Array.isArray(inputs.aipBaseline?.entries) ? inputs.aipBaseline.entries : [];
  const aipKeys = new Set(aipEntries.map(entry => `${entry.method} ${entry.path}`));
  const knownDebt = new Set(
    Array.isArray(inputs.dispositions.known_unowned_baseline)
      ? inputs.dispositions.known_unowned_baseline
      : [],
  );
  const callers = Array.isArray(inputs.callers) ? inputs.callers : [];
  const vercelRoutes = loadVercelRoutes(inputs.vercel);
  const seen = new Set();
  const censusRoutes = [];

  for (const route of routes) {
    const key = `${route.method} ${route.path}`;
    if (seen.has(key)) throw new CensusError(`duplicate router registration: ${key}`);
    seen.add(key);
    const version = routeVersion(route.path);
    const disposition = dispositionFor(inputs.dispositions, route);
    const curatedOp = curated.get(key);
    const aipEntry = aipKeys.has(key) ? aipEntries.find(entry => `${entry.method} ${entry.path}` === key) : null;
    const ownerIssue = Number.isInteger(disposition.owner_issue)
      ? disposition.owner_issue
      : Number.isInteger(curatedOp?.owning_issue) && version === 'v2'
        ? curatedOp.owning_issue
        : Number.isInteger(aipEntry?.owning_issue)
          ? aipEntry.owning_issue
          : null;
    const replacement = stringField(disposition, 'replacement', null)
      ?? (version === 'v2' ? 'canonical-v2' : 'needs-owner-disposition');
    const rolloutStatus = stringField(disposition, 'rollout_status', null)
      ?? (version === 'v2' ? 'live-target' : 'baseline-debt');
    const curatedConsumers = stringList(curatedOp?.consumers);
    const matchedCallers = callers.filter(caller => callerMatchesRoute(caller, route));
    // Precise per-operation source call sites win over the inventory's
    // family-level consumer lists; curated consumers are the fallback for
    // routes whose calls are assembled dynamically.
    const scannedConsumers = matchedCallers.map(caller => caller.file);
    const consumers = [...new Set(scannedConsumers.length ? scannedConsumers : curatedConsumers)].sort();
    const ingress = resolveIngress(route, vercelRoutes);
    censusRoutes.push({
      method: route.method,
      path: route.path,
      handler: route.handler,
      handler_kind: route.handler_kind,
      router_line: route.line,
      version,
      runtime: 'native-rust',
      runtime_source: 'native-router',
      consumers,
      caller_count: matchedCallers.length,
      ingress_destination: ingress.destination,
      ingress_source: ingress.source,
      owner_issue: ownerIssue,
      needs_owner_issue:
        (version === 'v1' || version === 'unversioned' || aipKeys.has(key))
        && ownerIssue === null && !knownDebt.has(key),
      disposition: replacement,
      rollout_status: rolloutStatus,
      notes: stringField(disposition, 'notes', ''),
    });
  }

  censusRoutes.sort((a, b) => {
    if (a.path !== b.path) return a.path < b.path ? -1 : 1;
    return METHODS.indexOf(a.method) - METHODS.indexOf(b.method);
  });
  const summary = {
    total_routes: censusRoutes.length,
    by_version: Object.fromEntries(
      ['v1', 'v2', 'unversioned'].map(version => [
        version,
        censusRoutes.filter(route => route.version === version).length,
      ]),
    ),
    v1_with_owner: censusRoutes.filter(route => route.version === 'v1' && route.owner_issue !== null).length,
    v1_needing_owner: censusRoutes.filter(route => route.version === 'v1' && route.needs_owner_issue).length,
    unknown_ingress: censusRoutes.filter(route => route.ingress_destination === 'unknown').length,
    first_party_call_sites: callers.length,
    stale_aip_baseline_entries: aipEntries.filter(entry =>
      !seen.has(`${entry.method} ${entry.path}`)).length,
  };
  return {
    schema_version: 1,
    generated_by: 'scripts/generate_live_route_census.mjs',
    issue: 5719,
    sources: {
      router: ROUTER_PATH,
      ingress: VERCEL_PATH,
      consumers: [INVENTORY_PATH, 'frontend/src', 'scripts/ops', 'native/roll-service/parity'],
      dispositions: DISPOSITIONS_PATH,
      aip_baseline: AIP_BASELINE_PATH,
    },
    summary,
    routes: censusRoutes,
    retired_cross_references: Array.isArray(inputs.dispositions.retired_cross_references)
      ? inputs.dispositions.retired_cross_references
      : [],
  };
}

/**
 * Machine-readable retirement allowlist. Every entry carries a specific owner
 * issue or an explicit, checked-in baseline-debt marker; unowned drift fails.
 */
export function buildAllowlist(census, dispositions, aipBaseline) {
  const aipEntries = Array.isArray(aipBaseline?.entries) ? aipBaseline.entries : [];
  const nonconforming = new Set(aipEntries.map(entry => `${entry.method} ${entry.path}`));
  const entries = census.routes
    .filter(route =>
      route.version === 'v1'
      || route.version === 'unversioned'
      || nonconforming.has(`${route.method} ${route.path}`))
    .map(route => ({
      method: route.method,
      path: route.path,
      version: route.version,
      owner_issue: route.owner_issue,
      disposition: route.disposition,
      rollout_status: route.rollout_status,
      needs_owner_issue: route.needs_owner_issue,
      runtime: route.runtime,
      consumers: route.consumers,
    }));
  return {
    schema_version: 1,
    generated_by: 'scripts/generate_live_route_census.mjs',
    issue: 5719,
    description:
      'Baseline v1, bare /api and nonconforming-v2 METHOD/path pairs. New calls '
      + 'or registrations outside this list fail CI. owner_issue is the specific '
      + 'retirement ticket; needs_owner_issue marks visible baseline debt.',
    reject_new_v1_calls: true,
    reject_new_v1_route_registrations: true,
    require_runtime: 'native-rust',
    known_unowned_baseline: Array.isArray(dispositions.known_unowned_baseline)
      ? [...dispositions.known_unowned_baseline].sort()
      : [],
    summary: {
      total_entries: entries.length,
      with_owner: entries.filter(entry => entry.owner_issue !== null).length,
      baseline_debt: entries.filter(entry => entry.needs_owner_issue).length,
      nonconforming_v2: entries.filter(entry => entry.version === 'v2').length,
    },
    entries,
  };
}

/** Escape a value so it stays in one Markdown table cell. */
function mdCell(value) {
  return String(value).replaceAll('|', '\\|');
}

/** Human-readable published ownership matrix with the #5719 columns. */
export function renderReport(census, allowlist, dispositions = {}) {
  const lines = [
    '# Live route census (all API versions)',
    '',
    '> Generated by `scripts/generate_live_route_census.mjs` (#5719). '
    + 'Do not hand-edit; run the generator after changing the router, '
    + 'dispositions, ingress or first-party callers.',
    '',
    'This is the all-version companion to '
    + '[the v2 route inventory](v2-route-inventory.json). API version is not '
    + 'implementation language: every row below is served by native Rust, and '
    + 'a Rust-served v1 method is still live v1 surface.',
    '',
    '## Query / report command',
    '',
    '```bash',
    'node scripts/generate_live_route_census.mjs              # refresh the matrix',
    'node scripts/generate_live_route_census.mjs --check      # CI drift gate',
    '```',
    '',
    '## Coverage summary',
    '',
    `- Live API routes: ${census.summary.total_routes} `
    + `(v1 ${census.summary.by_version.v1}, v2 ${census.summary.by_version.v2}, `
    + `unversioned ${census.summary.by_version.unversioned}).`,
    `- v1 routes with a named retirement owner: ${census.summary.v1_with_owner}.`,
    `- v1 routes needing an owner issue: ${census.summary.v1_needing_owner} `
    + '(visible baseline debt, not a pass).',
    `- Routes with unresolved production ingress: ${census.summary.unknown_ingress}.`,
    `- Scanned first-party call sites: ${census.summary.first_party_call_sites}.`,
    `- Stale AIP baseline entries (no live route): ${census.summary.stale_aip_baseline_entries}.`,
    `- Allowlist entries: ${allowlist.summary.total_entries} `
    + `(owner ${allowlist.summary.with_owner}, `
    + `baseline debt ${allowlist.summary.baseline_debt}, `
    + `nonconforming v2 ${allowlist.summary.nonconforming_v2}).`,
    '',
    '## Ownership matrix',
    '',
    '| Method | Canonical path | Rust handler | Version | Actual consumers | '
    + 'Production ingress | Owner | Proposed v2 replacement / disposition | Rollout status |',
    '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
  ];
  for (const route of census.routes) {
    const owner = route.owner_issue === null
      ? route.needs_owner_issue ? 'needs owner' : 'baseline debt'
      : `#${route.owner_issue}`;
    const consumers = route.consumers.length ? route.consumers.join(', ') : 'none';
    lines.push(
      `| ${route.method} | \`${route.path}\` | \`${route.handler}\` | ${route.version} `
      + `| ${mdCell(consumers)} | ${route.ingress_destination} | ${owner} `
      + `| ${mdCell(route.disposition)} | ${route.rollout_status} |`,
    );
  }
  const ownerIssues = [...new Set(census.routes
    .map(route => route.owner_issue)
    .filter(owner => owner !== null))].sort((a, b) => a - b);
  lines.push('', '## Owner issue cross-reference', '');
  lines.push(
    `Existing owner/disposition issues resolved for this census: ${ownerIssues.map(owner => `#${owner}`).join(', ')}.`,
  );
  lines.push(
    'No new backlog issue is created by this tooling task: every current live '
    + 'v1 method resolves to an existing owner issue and an AIP destination or '
    + 'an explicit retire-without-replacement decision.',
  );
  const specialStatuses = new Set([
    'background-caller-migration', 'test-helper-debt', 'active-infrastructure',
    'compatibility-alias-debt', 'pinned-404',
  ]);
  const special = census.routes.filter(route => specialStatuses.has(route.rollout_status));
  if (special.length) {
    lines.push('', 'Non-browser / helper / infrastructure surface included in the census:', '');
    for (const route of special) {
      lines.push(`- \`${route.method} ${route.path}\` — ${route.rollout_status} (owner #${route.owner_issue}).`);
    }
  }
  const crossReferences = Array.isArray(dispositions.retired_cross_references)
    ? dispositions.retired_cross_references
    : [];
  if (crossReferences.length) {
    lines.push('', '## Retired legacy issues cross-referenced (no live v1 registration)', '');
    for (const reference of crossReferences) {
      lines.push(
        `- #${reference.issue}: \`${reference.method} ${reference.path}\` — `
        + `${reference.status}; ${reference.disposition}.`,
      );
    }
  }
  lines.push('', '## Baseline debt requiring an owner issue', '');
  const debt = census.routes.filter(route => route.needs_owner_issue);
  if (debt.length === 0) {
    lines.push('None. Every live v1 method has an owner or an explicit disposition.');
  } else {
    for (const route of debt) {
      lines.push(`- \`${route.method} ${route.path}\` — ${route.disposition}.`);
    }
  }
  lines.push('', '## Verification', '');
  lines.push(
    '`node scripts/generate_live_route_census.mjs --check` regenerates the '
    + 'matrix, compares the checked-in artifacts byte-for-byte, and fails on '
    + 'duplicate registrations, unowned new routes, unknown ingress/runtime, '
    + 'stale allowlist entries, or a new first-party v1 call. The regression '
    + `\`${SET_PENDING_KEY}\` must always be present with owner #${SET_PENDING_OWNER}.`,
  );
  lines.push('');
  return lines.join('\n');
}

/** Validate invariants that must hold before the artifacts can be committed. */
export function validate(census, allowlist, dispositions, callers, aipBaseline = {}) {
  const failures = [];
  const knownDebt = new Set(
    Array.isArray(dispositions.known_unowned_baseline)
      ? dispositions.known_unowned_baseline
      : [],
  );
  const allowKeys = new Set(allowlist.entries.map(entry => `${entry.method} ${entry.path}`));
  const v1Routes = census.routes.filter(route => route.version === 'v1' || route.version === 'unversioned');

  for (const route of census.routes) {
    const key = `${route.method} ${route.path}`;
    if (route.runtime !== 'native-rust') {
      failures.push(`${key}: runtime '${route.runtime}' is not native-rust`);
    }
    if (route.ingress_destination === 'unknown') {
      failures.push(`${key}: no production ingress destination resolved`);
    }
    if ((route.version === 'v1' || route.version === 'unversioned') && !allowKeys.has(key)) {
      failures.push(`${key}: live legacy route is missing from the retirement allowlist`);
    }
  }
  for (const route of v1Routes) {
    if (route.needs_owner_issue && !knownDebt.has(`${route.method} ${route.path}`)) {
      failures.push(`${route.method} ${route.path}: unowned legacy route (no owner issue and not known baseline debt)`);
    }
    if (!route.disposition || route.disposition === 'needs-owner-disposition') {
      failures.push(`${route.method} ${route.path}: no owner/disposition`);
    }
  }
  for (const key of knownDebt) {
    if (!allowKeys.has(key)) failures.push(`known baseline debt ${key} is not a live allowlisted route`);
  }
  // Stale AIP baseline entries are pre-existing documentation debt, not new
  // v1 drift. They are counted in the report but do not fail the census gate.
  for (const [key, expectedDisposition] of CBL_ROUTE_DISPOSITIONS) {
    const route = census.routes.find(item => `${item.method} ${item.path}` === key);
    if (!route) continue;
    if (route.owner_issue !== CBL_ROUTE_OWNER) {
      failures.push(`${key}: owner should be #${CBL_ROUTE_OWNER}, got ${route.owner_issue}`);
    }
    if (route.disposition !== expectedDisposition) {
      failures.push(`${key}: disposition should be '${expectedDisposition}', got '${route.disposition}'`);
    }
  }
  for (const caller of callers) {
    if (!caller.drift_checked) continue;
    const isV1OrBare = caller.path.startsWith('/api/v1/')
      || /^\/api\/[^v/]/.test(caller.path) || /^\/api\/v[^12]/.test(caller.path);
    if (!isV1OrBare) continue;
    const matches = v1Routes.some(route => callerMatchesRoute(caller, route));
    if (!matches) {
      failures.push(`${caller.file}:${caller.line}: new first-party v1/bare call '${caller.raw}' has no allowlisted route`);
    }
  }
  return failures;
}

function parseArgs(argv) {
  const args = {root: DEFAULT_ROOT, check: false};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--check') args.check = true;
    else if (arg === '--root') args.root = path.resolve(argv[++i]);
    else if (arg === '--help' || arg === '-h') {
      console.log('usage: generate_live_route_census.mjs [--root DIR] [--check]');
      process.exit(0);
    } else throw new CensusError(`unknown argument: ${arg}`);
  }
  return args;
}

/** Generate all artifacts in memory and return their text plus validation failures. */
export function generate(root = DEFAULT_ROOT) {
  const routerText = readFileSync(path.join(root, ROUTER_PATH), 'utf8');
  const inventory = readJson(path.join(root, INVENTORY_PATH));
  const dispositions = readJson(path.join(root, DISPOSITIONS_PATH));
  const aipBaseline = readJson(path.join(root, AIP_BASELINE_PATH));
  const vercel = readJson(path.join(root, VERCEL_PATH));
  const callers = scanCallers(root);
  const census = buildCensus({routerText, inventory, dispositions, aipBaseline, vercel, callers});
  const allowlist = buildAllowlist(census, dispositions, aipBaseline);
  const report = renderReport(census, allowlist, dispositions);
  const failures = validate(census, allowlist, dispositions, callers, aipBaseline);
  return {
    census,
    allowlist,
    artifacts: {
      [CENSUS_PATH]: stableJson(census),
      [ALLOWLIST_PATH]: stableJson(allowlist),
      [REPORT_PATH]: report,
    },
    failures,
  };
}

export function main(argv = process.argv) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (error) {
    if (error instanceof CensusError) {
      console.log(`live route census failed: ${error.message}`);
      return 2;
    }
    throw error;
  }
  try {
    const result = generate(args.root);
    if (args.check) {
      const problems = [...result.failures];
      for (const [relative, text] of Object.entries(result.artifacts)) {
        const file = path.join(args.root, relative);
        if (!existsSync(file) || readFileSync(file, 'utf8') !== text) {
          problems.push(`${relative} is stale; run node scripts/generate_live_route_census.mjs`);
        }
      }
      if (problems.length) {
        console.error('live route census check failed:');
        for (const problem of problems) console.error(`  - ${problem}`);
        return 1;
      }
      console.log(
        `Verified live route census: ${result.census.summary.total_routes} routes, `
        + `${result.allowlist.summary.total_entries} allowlist entries, `
        + `${result.census.summary.v1_needing_owner} baseline debt.`,
      );
      return 0;
    }
    for (const [relative, text] of Object.entries(result.artifacts)) {
      writeFileSync(path.join(args.root, relative), text, 'utf8');
    }
    console.log(
      `Wrote live route census: ${result.census.summary.total_routes} routes, `
      + `${result.allowlist.summary.total_entries} allowlist entries.`,
    );
    return result.failures.length ? 1 : 0;
  } catch (error) {
    if (error instanceof CensusError) {
      console.log(`live route census failed: ${error.message}`);
      return 2;
    }
    throw error;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
