/**
 * Shared helpers for per-area route-fragment regression tests.
 *
 * Each route area keeps its own `<area>.test.mjs` file in this directory, so a
 * PR that migrates one area never edits a test file another area's PR edits
 * (owner directive 2026-11-19). CI runs every `*.test.mjs` file here. The
 * fixture tests in scripts/generate_route_burndown.test.mjs prove the
 * generator is deterministic; these prove active route declarations retain
 * their intended contracts before bot-owned outputs regenerate post-merge.
 */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

export function liveFragment(name) {
  return JSON.parse(readFileSync(path.join(repoRoot, 'docs/api/route-fragments', name + '.json'), 'utf8'));
}

export function liveOperation(fragment, method, route) {
  const op = fragment.operations.find(item => item.method === method && item.path === route);
  assert.ok(op, 'missing ' + method + ' ' + route + ' from ' + fragment.family);
  return op;
}
