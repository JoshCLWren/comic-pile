import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {
  ALLOWLIST,
  checkNativeRouteDbTests,
  matchesRoute,
  modulesFromOpenApi,
  routeModulesFromLib,
  testCoversModule,
} from './check_native_route_db_tests.mjs';

const SCRIPT = fileURLToPath(new URL('./check_native_route_db_tests.mjs', import.meta.url));

const LIB_RS = `\
pub mod alpha;
pub mod beta;
pub mod gamma;

use beta::{helper_beta};

pub fn router() {
    Router::new()
        .route("/health", get(|| async { "ok" }))
        .route(
            "/api/v1/alphas/{id}",
            get(alpha::get_alpha).post(alpha::create_alpha),
        )
        .route("/api/v1/betas", get(helper_beta))
        .route("/api/v1/gammas", get(gamma::handlers::list))
}

#[cfg(test)]
mod tests {
    #[tokio::test]
    async fn inline_router_is_not_a_route_module() {
        let app = Router::new().route("/api/v1/phantom", get(|| async { "x" }));
    }
}
`;

const OPENAPI_RS = `\
#[openapi(paths(crate::alpha::get_documentation, crate::doc_only::doc,))]
struct Api;
`;

function fixture(t, tests) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'native-route-db-guard-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const src = path.join(root, 'native', 'roll-service', 'src');
  const testDir = path.join(root, 'native', 'roll-service', 'tests');
  fs.mkdirSync(src, {recursive: true});
  fs.mkdirSync(testDir, {recursive: true});
  fs.writeFileSync(path.join(src, 'lib.rs'), LIB_RS);
  fs.writeFileSync(path.join(src, 'same_path_openapi.rs'), OPENAPI_RS);
  for (const [name, source] of Object.entries(tests)) {
    fs.writeFileSync(path.join(testDir, name), source);
  }
  return root;
}

const DB_ALPHA_TEST = `\
let url = comicpile_roll_service::test_support::database_url().await;
let response = router(state).oneshot(
    Request::builder().uri("/api/v1/alphas/42").body(Body::empty()),
);
`;

test('parses route modules from lib.rs, ignoring inline closures and test-only routers', () => {
  const modules = routeModulesFromLib(LIB_RS);
  assert.deepEqual(modules.map(entry => entry.module), ['alpha', 'beta', 'gamma']);
  assert.deepEqual(modules[0].routes, ['/api/v1/alphas/{id}']);
  assert.deepEqual(modules[1].routes, ['/api/v1/betas']); // imported bare handler
  assert.deepEqual(modules[2].routes, ['/api/v1/gammas']); // nested handler path
  assert(!modules.some(entry => entry.module === 'phantom'));
});

test('route parameter matching tolerates concrete ids, format placeholders and query strings', () => {
  assert(matchesRoute('/api/v1/alphas/42', '/api/v1/alphas/{id}'));
  assert(matchesRoute('/api/v1/alphas/{}', '/api/v1/alphas/{id}'));
  assert(matchesRoute('/api/v1/alphas/7?expand=1', '/api/v1/alphas/{id}'));
  assert(!matchesRoute('/api/v1/alphas', '/api/v1/alphas/{id}'));
  assert(!matchesRoute('/api/v1/alphas/7/children', '/api/v1/alphas/{id}'));
  assert(!matchesRoute('/api/v2/alphas/7', '/api/v1/alphas/{id}'));
});

test('test coverage requires both the real DB harness and a matching route URI', () => {
  const routes = ['/api/v1/alphas/{id}'];
  assert(testCoversModule(DB_ALPHA_TEST, routes));
  assert(!testCoversModule('let uri = "/api/v1/alphas/42";\n', routes));
  assert(!testCoversModule('test_support::database_url(); let uri = "/health";', routes));
  assert(!testCoversModule('// RUST_ROLL_TEST_DATABASE_URL in a doc comment; uri("/api/v1/alphas/7")', routes));
  assert(testCoversModule('std::env::var("RUST_ROLL_TEST_DATABASE_URL"); uri("/api/v1/alphas/7")', routes));
  assert(testCoversModule('test_support::reset_for_test(&state).await; uri("/api/v1/alphas/7")', routes));
});

test('OpenAPI-only module names are reported without becoming HTTP route modules', () => {
  const modules = modulesFromOpenApi(OPENAPI_RS);
  assert.deepEqual(modules, ['alpha', 'doc_only']);
});

test('guard reports uncovered modules with their routes and accepts covered modules', t => {
  const root = fixture(t, {'alpha_http.rs': DB_ALPHA_TEST});
  const result = checkNativeRouteDbTests(root, new Map());
  assert.deepEqual(result.gaps.map(gap => gap.module), ['beta', 'gamma']);
  assert.deepEqual(result.gaps.find(gap => gap.module === 'gamma').routes, ['/api/v1/gammas']);
  assert.deepEqual(result.covered, [{module: 'alpha', test: 'alpha_http.rs'}]);
  assert.deepEqual(result.openapiOnly, ['doc_only']);
  assert.equal(result.moduleCount, 3);
});

test('guard honours an explicit allowlist and flags stale allowlist entries', t => {
  const root = fixture(t, {'alpha_http.rs': DB_ALPHA_TEST});
  const allowlist = new Map([
    ['alpha', {kind: 'gap', reason: 'TODO: tracked for a follow-up DB test'}],
    ['beta', {kind: 'genuine', reason: 'handler reads no database state at all'}],
  ]);
  const result = checkNativeRouteDbTests(root, allowlist);
  assert.deepEqual(result.gaps.map(gap => gap.module), ['gamma']);
  assert.deepEqual(result.staleAllowlist, ['alpha']);
});

test('guard fails closed on an unjustified allowlist entry', t => {
  const root = fixture(t, {'alpha_http.rs': DB_ALPHA_TEST});
  assert.throws(
    () => checkNativeRouteDbTests(root, new Map([['beta', {kind: 'gap', reason: 'later'}]])),
    /Invalid allowlist entry|must include a TODO/,
  );
});

test('every allowlist entry carries a reason; gaps reference the follow-up PR', () => {
  for (const [module, entry] of ALLOWLIST) {
    assert(module && typeof module === 'string', 'allowlist key must be a module name');
    assert(['genuine', 'gap'].includes(entry.kind), `${module}: unknown allowlist kind`);
    assert(entry.reason.length > 20, `${module}: allowlist entry needs a concrete reason`);
    if (entry.kind === 'gap') {
      assert.match(entry.reason, /TODO/, `${module}: gap needs a TODO`);
      assert.match(entry.reason, /DB-backed HTTP test|PostgreSQL-backed HTTP test/, `${module}: gap needs the test action`);
      assert.match(entry.reason, /#5351/, `${module}: gap needs the root-cause issue`);
    }
  }
});

test('CLI exits 0 when every module is covered and 1 when a gap is unallowlisted', t => {
  const coveredRoot = fixture(t, {
    'alpha_http.rs': DB_ALPHA_TEST,
    'beta_http.rs': `test_support::database_url(); uri("/api/v1/betas")`,
    'gamma_http.rs': `test_support::database_url(); uri("/api/v1/gammas")`,
  });
  const green = spawnSync(process.execPath, [SCRIPT, '--root', coveredRoot], {encoding: 'utf8'});
  assert.equal(green.status, 0, green.stderr);
  assert.match(green.stdout, /0 gap\(s\)/);

  const gapRoot = fixture(t, {'alpha_http.rs': DB_ALPHA_TEST});
  const red = spawnSync(process.execPath, [SCRIPT, '--root', gapRoot], {encoding: 'utf8'});
  assert.equal(red.status, 1);
  assert.match(red.stderr, /MISSING  beta/);
  assert.match(red.stderr, /MISSING  gamma/);
});
