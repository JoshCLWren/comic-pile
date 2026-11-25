#!/usr/bin/env node
/**
 * CI guard: every native Rust module that serves an HTTP route must have at
 * least one PostgreSQL-backed HTTP test in native/roll-service/tests/*.rs.
 *
 * Root cause (#5351): `creators_v2` shipped with zero database-backed tests,
 * so an int4/i64 decoding panic on every request passed CI. A unit test that
 * never opens a connection cannot catch that class of defect: the canonical
 * schema and its real column types only exist in the disposable test database.
 *
 * This checker is Node JS on purpose: the Python runtime is being removed
 * (#5431), and the Rust test harness is itself what we are guarding.
 *
 * A test file counts for a module only when BOTH hold:
 *   1. it opts into the real database harness (`RUST_ROLL_TEST_DATABASE_URL`
 *      or a `test_support` helper that requires it), and
 *   2. it contains a literal request URI matching one of the module's routes
 *      registered in `lib.rs::router`. Route parameters match any one segment;
 *      the HTTP method is intentionally not part of the match (this guard
 *      proves a module has a DB-backed HTTP surface, not per-method coverage).
 *
 * Modules that genuinely need no DB test, plus the current gaps, are listed
 * in ALLOWLIST with an explicit reason. Every gap carries a TODO referencing
 * the PR that adds this guard; those tests are deliberately not written there.
 */
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import {fileURLToPath} from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const LIB_RS = path.join('native', 'roll-service', 'src', 'lib.rs');
const OPENAPI_RS = path.join('native', 'roll-service', 'src', 'same_path_openapi.rs');
const TESTS_DIR = path.join('native', 'roll-service', 'tests');

const FOLLOWUP = 'TODO("ci: require a DB-backed HTTP test for every native route module")';

/**
 * Modules exempt from the DB-backed HTTP test requirement, with a reason.
 *
 * `kind: 'genuine'` means the module truly needs no database test.
 * `kind: 'gap'` means the test is missing and must be written in a follow-up;
 * those entries include a TODO referencing this CI-guard PR and #5351.
 */
export const ALLOWLIST = new Map([
  // Genuine exemptions would go here with a concrete explanation, e.g.:
  // ['metrics', {kind: 'genuine', reason: 'in-process counters, no SQL'}],
  // Inline health probes in lib.rs have no module and touch no database, so
  // they are not entries here at all.
  ...[
    'activity',
    'analytics',
    'bug_reports',
    'catalog_commit',
    'comicvine_issue',
    'comicvine_repair',
    'comicvine_resolution',
    'continuity_rules',
    'creators',
    'demo',
    'dice_api',
    'dismiss_pending',
    'identity_inbox',
    'issue_read',
    'legacy_dependencies',
    'metrics',
    'preferences',
    'reading_mode',
    'reading_orders',
    'reading_plan_sync',
    'releases',
    'roll_reset',
    'session_detail',
    'session_details',
    'session_history',
    'session_list',
    'taste_discoveries',
    'undo_apply',
    'undo_snapshots',
  ].map(module => [
    module,
    {
      kind: 'gap',
      reason: `${FOLLOWUP}: add a PostgreSQL-backed HTTP test for ${module} ` +
        '(root cause #5351: route modules shipped with no DB test).',
    },
  ]),
]);

/**
 * Map every handler name imported into lib.rs to its root module.
 *
 * Both Rust import forms matter: `use alpha::list;` and
 * `use alpha::{list as list_alpha};`. The name the router uses is the local
 * one (the alias, when present), so that is what must be recorded here.
 */
function importedNames(source) {
  const names = new Map();
  const record = (local, module) => {
    if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(local) && local !== 'self' && !names.has(local)) {
      names.set(local, module);
    }
  };
  const brace = /use\s+([A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*)::\{([^}]*)\}\s*;/g;
  for (const match of source.matchAll(brace)) {
    const module = match[1].split('::')[0];
    for (const raw of match[2].split(',')) {
      const parts = raw.trim().split(/\s+as\s+/).map(part => part.trim());
      record(parts.length > 1 ? parts[1] : parts[0], module);
    }
  }
  const single = /use\s+([A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*)\s*;/g;
  for (const match of source.matchAll(single)) {
    const path = match[1].split('::');
    record(path.at(-1), path[0]);
  }
  const aliased = /use\s+([A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)\s*;/g;
  for (const match of source.matchAll(aliased)) {
    record(match[2], match[1].split('::')[0]);
  }
  return names;
}

/** Return the text of the balanced `(...)` starting at `open`. */
function balancedParen(source, open) {
  let depth = 0;
  let quote = false;
  let escaped = false;
  for (let index = open; index < source.length; index += 1) {
    const ch = source[index];
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') quote = false;
      continue;
    }
    if (ch === '"') {
      quote = true;
    } else if (ch === '(') {
      depth += 1;
    } else if (ch === ')') {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, index);
    }
  }
  return '';
}

/**
 * Extract `{module -> [registered route paths]}` from the production router
 * in lib.rs. Only the `router` function body is scanned, so the inline test
 * routers in `#[cfg(test)] mod tests` cannot create phantom modules.
 */
export function routeModulesFromLib(source) {
  const start = source.indexOf('pub fn router(');
  const end = source.indexOf('#[cfg(test)]', start);
  const router = start === -1 ? source : source.slice(start, end === -1 ? undefined : end);
  const imports = importedNames(source);
  const modules = new Map();

  for (let cursor = 0; cursor < router.length; ) {
    const at = router.indexOf('.route(', cursor);
    if (at === -1) break;
    const args = balancedParen(router, at + '.route'.length);
    cursor = at + '.route'.length + args.length + 2;

    const pathMatch = args.match(/"([^"\n]+)"/);
    if (!pathMatch) continue;
    const routePath = pathMatch[1];

    // A single .route() may chain several method handlers. Inline closures
    // (health probes) are not attributable to a module and are skipped.
    for (const call of args.matchAll(/\b(?:get|post|put|patch|delete)\s*\(([^),]+)/g)) {
      const handler = call[1].trim();
      const segments = handler.split('::');
      let module = null;
      if (segments.length > 1 && /^[A-Za-z_][A-Za-z0-9_]*$/.test(segments[0])) {
        module = segments[0];
      } else if (imports.has(handler)) {
        // Bare handler imported by `use module::...` (e.g. custom_cbl).
        module = imports.get(handler);
      } else if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(handler)) {
        // A named handler we cannot attribute must never silently escape the
        // guard. Inline closures start with `|` and are intentionally skipped.
        throw new Error(`Cannot resolve route handler ${handler} to a module in lib.rs`);
      }
      if (!module || module === 'axum' || module === 'middleware') continue;
      if (!modules.has(module)) modules.set(module, new Set());
      modules.get(module).add(routePath);
    }
  }
  return [...modules.entries()]
    .map(([module, routes]) => ({module, routes: [...routes].sort()}))
    .sort((a, b) => a.module.localeCompare(b.module));
}

/** Modules named in the generated same-path OpenAPI document. */
export function modulesFromOpenApi(source) {
  const modules = new Set();
  for (const match of source.matchAll(/crate::([A-Za-z_][A-Za-z0-9_]*)::/g)) {
    modules.add(match[1]);
  }
  return [...modules].sort();
}

/** True when a request URI matches a registered route; `{param}` is a wildcard. */
export function matchesRoute(requestUri, routePath) {
  const actual = requestUri.split('?')[0].split('/');
  const expected = routePath.split('/');
  if (actual.length !== expected.length) return false;
  return expected.every((segment, index) =>
    segment.includes('{') ? Boolean(actual[index]) : segment === actual[index],
  );
}

/** Flatten the discovered modules into the single route table the router uses. */
export function buildRouteTable(discovered) {
  return discovered.flatMap(({module, routes}) => routes.map(route => ({module, route})));
}

/**
 * Resolve a request URI against the WHOLE route table, not per module.
 *
 * Axum's matchit prefers static segments over parameters. We mirror that by
 * picking the candidates with the most static segments; a wildcard from one
 * module must not steal a fixed path owned by another (e.g.
 * `/api/v1/issue-identity/cbl-sources/folders` belongs to `cbl_catalog`, not
 * to `issue_identity`'s `/{list_id}`). Ties are possible when two modules
 * register the same path for different methods; without parsing the test's
 * HTTP method both modules are credited, which cannot create a false pass for
 * a module that has no test of its own route at all.
 */
export function resolveRouteOwners(requestUri, routeTable) {
  const candidates = routeTable.filter(entry => matchesRoute(requestUri, entry.route));
  if (!candidates.length) return [];
  const staticCount = entry => entry.route.split('/').filter(segment => !segment.includes('{')).length;
  const best = Math.max(...candidates.map(staticCount));
  return [...new Set(candidates.filter(entry => staticCount(entry) === best).map(entry => entry.module))];
}

const DB_HARNESS = [
  'test_support::database_url',
  'test_support::test_state',
  'test_support::reset_for_test',
  'test_support::required_test_admin_url',
];
const DB_ENV_ACCESS = /std::env::var\(\s*"RUST_ROLL_TEST_DATABASE_URL"/;

/**
 * Strip Rust line and block comments while preserving string literals, so
 * commented-out tests and doc comments cannot satisfy the guard.
 */
export function stripRustComments(source) {
  let result = '';
  let index = 0;
  let inString = false;
  let inRawString = false;
  let rawHashes = 0;
  let inLineComment = false;
  let blockDepth = 0;
  while (index < source.length) {
    const ch = source[index];
    const next = source[index + 1];
    if (inLineComment) {
      if (ch === '\n') {
        inLineComment = false;
        result += ch;
      }
      index += 1;
      continue;
    }
    if (blockDepth > 0) {
      if (ch === '/' && next === '*') {
        blockDepth += 1;
        index += 2;
        continue;
      }
      if (ch === '*' && next === '/') {
        blockDepth -= 1;
        index += 2;
        continue;
      }
      if (ch === '\n') result += ch;
      index += 1;
      continue;
    }
    if (inString) {
      result += ch;
      if (ch === '\\') {
        result += next ?? '';
        index += 2;
        continue;
      }
      if (ch === '"') inString = false;
      index += 1;
      continue;
    }
    if (inRawString) {
      result += ch;
      if (ch === '"') {
        let hashes = 0;
        while (hashes < rawHashes && source[index + 1 + hashes] === '#') hashes += 1;
        if (hashes === rawHashes) {
          result += '#'.repeat(hashes);
          index += 1 + hashes;
          inRawString = false;
          continue;
        }
      }
      index += 1;
      continue;
    }
    if (ch === '/' && next === '/') {
      inLineComment = true;
      index += 2;
      continue;
    }
    if (ch === '/' && next === '*') {
      blockDepth = 1;
      index += 2;
      continue;
    }
    if (ch === 'r') {
      let hashes = 0;
      let probe = index + 1;
      while (source[probe] === '#') {
        hashes += 1;
        probe += 1;
      }
      if (source[probe] === '"') {
        inRawString = true;
        rawHashes = hashes;
        result += source.slice(index, probe + 1);
        index = probe + 1;
        continue;
      }
    }
    if (ch === '"') {
      inString = true;
      result += ch;
      index += 1;
      continue;
    }
    result += ch;
    index += 1;
  }
  return result;
}

/**
 * Decide whether one test file both uses the real database harness and
 * exercises a route actually owned by `module` in the full route table.
 *
 * A doc comment that merely mentions `RUST_ROLL_TEST_DATABASE_URL` is not
 * enough: the file must actually call a `test_support` helper that provisions
 * the canonical schema or read that environment variable. Commented-out code
 * is ignored so the guard cannot be satisfied by inactive tests.
 */
export function testCoversModule(testSource, module, routeTable) {
  const activeSource = stripRustComments(testSource);
  if (!DB_HARNESS.some(marker => activeSource.includes(marker)) && !DB_ENV_ACCESS.test(activeSource)) {
    return false;
  }
  return [...activeSource.matchAll(/"([^"\n]+)"/g)].some(
    match => match[1].startsWith('/api/')
      && resolveRouteOwners(match[1], routeTable).includes(module),
  );
}

/** Run the whole guard against a checkout root. */
export function checkNativeRouteDbTests(root, allowlist = ALLOWLIST) {
  for (const [module, entry] of allowlist) {
    if (!entry || !['genuine', 'gap'].includes(entry.kind)
      || Object.prototype.toString.call(entry.reason) !== '[object String]' || entry.reason.trim().length < 20) {
      throw new Error(`Invalid allowlist entry for ${module}: need a kind and a concrete reason`);
    }
    if (entry.kind === 'gap' && !entry.reason.includes('TODO')) {
      throw new Error(`Gap allowlist entry for ${module} must include a TODO follow-up`);
    }
  }
  const lib = fs.readFileSync(path.join(root, LIB_RS), 'utf8');
  const openapi = fs.readFileSync(path.join(root, OPENAPI_RS), 'utf8');
  const discovered = routeModulesFromLib(lib);
  const routeTable = buildRouteTable(discovered);
  const routeNames = new Set(discovered.map(entry => entry.module));
  // OpenAPI documentation cannot invent HTTP routes: only modules registered
  // in the router are checked. Doc-only modules are reported for visibility.
  const openapiOnly = modulesFromOpenApi(openapi).filter(module => !routeNames.has(module));

  const testSources = fs
    .readdirSync(path.join(root, TESTS_DIR))
    .filter(name => name.endsWith('.rs'))
    .map(name => ({name, source: fs.readFileSync(path.join(root, TESTS_DIR, name), 'utf8')}));

  const gaps = [];
  const covered = [];
  const staleAllowlist = [];
  for (const {module, routes} of discovered) {
    const evidence = testSources.find(file => testCoversModule(file.source, module, routeTable));
    if (evidence) {
      covered.push({module, test: evidence.name});
      if (allowlist.has(module)) staleAllowlist.push(module);
    } else if (!allowlist.has(module)) {
      gaps.push({module, routes});
    }
  }
  return {gaps, covered, staleAllowlist, openapiOnly, moduleCount: discovered.length};
}

function main() {
  const args = process.argv.slice(2);
  const rootIndex = args.indexOf('--root');
  const root = rootIndex === -1 ? REPO_ROOT : path.resolve(args[rootIndex + 1]);
  const {gaps, covered, staleAllowlist, openapiOnly, moduleCount} = checkNativeRouteDbTests(root);
  console.log(
    `Native route DB-test guard: ${moduleCount} route modules, ` +
      `${covered.length} with a DB-backed HTTP test, ${gaps.length} gap(s).`,
  );
  for (const {module, test} of covered) console.log(`  OK       ${module} -> ${test}`);
  for (const {module, routes} of gaps) {
    console.error(`  MISSING  ${module}: ${routes.join(', ')}`);
  }
  if (openapiOnly.length) {
    console.log(`  OpenAPI-only (no HTTP route, not checked): ${openapiOnly.join(', ')}`);
  }
  if (staleAllowlist.length) {
    console.log(
      `  NOTE: allowlist entries now covered by tests (safe to remove): ` +
        staleAllowlist.join(', '),
    );
  }
  if (gaps.length) {
    console.error(
      '\nEvery native route module needs a PostgreSQL-backed HTTP test in ' +
        'native/roll-service/tests/*.rs (see scripts/check_native_route_db_tests.mjs).',
    );
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
