import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {_generateVercelDocument, _loadRouteFragments} from './generate_route_burndown.mjs';
import {slimNativeRollRoutes, parseSegments, routesMayOverlap} from './vercel_slim_routes.mjs';

const ROLL = '/api/native_roll.rs';
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];
const json = file => JSON.parse(readFileSync(file, 'utf8'));

function resolve(routes, method, path) {
  for (const route of routes) {
    if (Object.prototype.toString.call(route.src) !== '[object String]') continue;
    if (!new RegExp(`^(?:${route.src})$`).test(path)) continue;
    if (route.methods && route.methods.length && !route.methods.includes(method)) continue;
    return route.dest;
  }
  return null;
}

function concretePaths(template) {
  return ['1', 'abc', '42'].map(fill => template.replace(/\{[^}]+\}/g, fill));
}

function allTemplates(inventory, fragments) {
  const templates = new Set();
  for (const op of inventory.operations) templates.add(op.path);
  for (const bucket of ['v1_operations', 'unversioned_operations']) {
    for (const op of inventory.full_surface[bucket]) templates.add(op.path);
  }
  for (const fragment of fragments) for (const op of fragment.operations) templates.add(op.path);
  return [...templates];
}

test('slim vercel routes resolve identically to the full route list', () => {
  const fragments = _loadRouteFragments('docs/api/route-fragments');
  const previous = json('vercel.json');
  const full = _generateVercelDocument(previous, fragments, {slim: false}).routes;
  const slim = _generateVercelDocument(previous, fragments, {slim: true}).routes;
  assert.ok(slim.length < full.length, 'slim list must drop redundant native_roll routes');
  const inventory = json('docs/api/v2-route-inventory.json');
  const templates = allTemplates(inventory, fragments);
  let checked = 0;
  for (const template of templates) {
    for (const concrete of concretePaths(template)) {
      for (const method of METHODS) {
        assert.equal(
          resolve(slim, method, concrete),
          resolve(full, method, concrete),
          `${method} ${concrete} resolves differently`,
        );
        checked += 1;
      }
    }
  }
  assert.ok(checked > 1000);
  // Unknown paths still reach the catch-all.
  assert.equal(resolve(slim, 'GET', '/api/v2/never-registered'), ROLL);
});

test('slim list keeps python, issue, catch-all and non-api routes and every needed roll route', () => {
  const fragments = _loadRouteFragments('docs/api/route-fragments');
  const previous = json('vercel.json');
  const full = _generateVercelDocument(previous, fragments, {slim: false}).routes;
  const slim = _generateVercelDocument(previous, fragments, {slim: true}).routes;
  const keep = route => route.dest !== ROLL || route.src === '/api(?:/.*)?';
  assert.deepEqual(slim.filter(keep), full.filter(keep));
  const slimSet = new Set(slim.map(route => JSON.stringify(route)));
  for (const route of slim) assert.ok(slimSet.has(JSON.stringify(route)));
  // A roll route shadowed by a later python route must survive.
  const kept = slim.filter(route => route.dest === ROLL && route.src !== '/api(?:/.*)?');
  assert.ok(kept.length > 0);
});

test('synthetic: a roll route is dropped unless a later python or issue route overlaps', () => {
  const free = {src: '^/api/v2/free$', methods: ['GET'], dest: ROLL};
  const shadowed = {src: '^/api/v1/things/summaries$', methods: ['GET'], dest: ROLL};
  const otherMethod = {src: '^/api/v1/other$', methods: ['POST'], dest: ROLL};
  const python = {src: '^/api/v1/things/[^/]+$', methods: ['GET', 'OPTIONS'], dest: '/api/index.py'};
  const pythonOther = {src: '^/api/v1/other$', methods: ['GET'], dest: '/api/index.py'};
  const catchAll = {src: '/api(?:/.*)?', dest: ROLL};
  const spa = {src: '/(.*)', dest: '/index.html'};
  const routes = [free, shadowed, otherMethod, python, pythonOther, catchAll, spa];
  const out = slimNativeRollRoutes(routes, new Set([free, shadowed, otherMethod]));
  assert.deepEqual(out, [shadowed, python, pythonOther, catchAll, spa]);
});

test('crossed-parameter routes overlap even though no template produces a shared sample', () => {
  const roll = {src: '^/api/a/[^/]+/b$', methods: ['GET'], dest: ROLL};
  const python = {src: '^/api/a/c/[^/]+$', methods: ['GET', 'OPTIONS'], dest: '/api/index.py'};
  assert.equal(routesMayOverlap(roll, python), true);
  const catchAll = {src: '/api(?:/.*)?', dest: ROLL};
  assert.deepEqual(slimNativeRollRoutes([roll, python, catchAll], new Set([roll])), [roll, python, catchAll]);
});

test('segment unifier proves disjointness and treats unknown shapes as overlapping', () => {
  const route = (src, methods = ['GET']) => ({src, methods, dest: '/api/index.py'});
  assert.equal(routesMayOverlap(route('^/api/a/[0-9]+$'), route('^/api/a/x$')), false);
  assert.equal(routesMayOverlap(route('^/api/a/[0-9]+$'), route('^/api/a/12$')), true);
  assert.equal(routesMayOverlap(route('^/api/a$'), route('^/api/a/[^/]+$')), false);
  assert.equal(routesMayOverlap(route('^/api/a/[^/]+$'), route('^/api/a/.+$')), true);
  assert.equal(routesMayOverlap(route('^/api/a$'), route('^/api/a/.+$')), false);
  assert.equal(routesMayOverlap(route('^/api/a/(?!b$)[^/]+$'), route('^/api/a/b$')), true);
  assert.equal(parseSegments('^/api/v1/identity\\-inbox/[^/]+$').length, 5);
  assert.equal(routesMayOverlap(route('^/api/a$', ['GET']), route('^/api/a$', ['POST'])), false);
});

test('character-class escapes are unknown shapes, so the roll route is kept', () => {
  const roll = {src: '^/api/a/\\d$', methods: ['GET'], dest: ROLL};
  const python = {src: '^/api/a/5$', methods: ['GET', 'OPTIONS'], dest: '/api/index.py'};
  assert.equal(parseSegments(roll.src), null);
  assert.equal(routesMayOverlap(roll, python), true);
  const catchAll = {src: '/api(?:/.*)?', dest: ROLL};
  assert.deepEqual(slimNativeRollRoutes([roll, python, catchAll], new Set([roll])), [roll, python, catchAll]);
});

test('regenerating from an already-slim vercel.json is stable and still equivalent', () => {
  const fragments = _loadRouteFragments('docs/api/route-fragments');
  const slimDocument = _generateVercelDocument(json('vercel.json'), fragments, {slim: true});
  const again = _generateVercelDocument(slimDocument, fragments, {slim: true});
  assert.deepEqual(again.routes, slimDocument.routes);
  const fullFromSlim = _generateVercelDocument(slimDocument, fragments, {slim: false}).routes;
  const fullFromOriginal = _generateVercelDocument(json('vercel.json'), fragments, {slim: false}).routes;
  for (const template of allTemplates(json('docs/api/v2-route-inventory.json'), fragments)) {
    for (const concrete of concretePaths(template)) {
      for (const method of METHODS) {
        assert.equal(
          resolve(fullFromSlim, method, concrete),
          resolve(fullFromOriginal, method, concrete),
          `${method} ${concrete} changed after regenerating from slim input`,
        );
      }
    }
  }
  // A fragment operation without its own src must never inherit the catch-all.
  assert.ok(!fullFromSlim.some(route => route.src === '/api(?:/.*)?' && route.methods));
});
