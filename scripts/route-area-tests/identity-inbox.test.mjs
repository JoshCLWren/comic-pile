import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {repoRoot, liveFragment, liveOperation} from './helpers.mjs';

test('identity-inbox v2 resources retain all seven native contracts and Rust ingress', () => {
  const native = JSON.parse(readFileSync(
    path.join(repoRoot, 'native/contracts/v2-runtime.openapi.json'), 'utf8',
  ));
  const fragment = liveFragment('identity-inbox');
  const expected = [
    ['GET', '/api/v2/identity-inbox'],
    ['GET', '/api/v2/identity-inbox/issue-matches'],
    ['GET', '/api/v2/identity-inbox/{mapping_id}'],
    ['POST', '/api/v2/identity-inbox/{mapping_id}/confirmations'],
    ['POST', '/api/v2/identity-inbox/{mapping_id}/deferrals'],
    ['POST', '/api/v2/identity-inbox/{mapping_id}/rejections'],
    ['POST', '/api/v2/identity-inbox/{mapping_id}/skips'],
  ];
  for (const [method, route] of expected) {
    const op = native.paths[route]?.[method.toLowerCase()];
    assert.ok(op?.operationId, 'missing native operationId for ' + method + ' ' + route);
    assert.ok(Object.keys(op.responses).some(code => code.startsWith('2')), route);
    assert.equal(liveOperation(fragment, method, route).dest, '/api/native_roll.rs', route);
  }
});
