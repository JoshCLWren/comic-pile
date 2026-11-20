import assert from 'node:assert/strict';
import {test} from 'node:test';
import {liveFragment, liveOperation} from './helpers.mjs';

test('real creator source retains all eleven native v2 browser routes', () => {
  const fragment = liveFragment('creators');
  const routes = fragment.operations.filter(op => op.path.startsWith('/api/v2/creators'));
  assert.equal(routes.length, 11);
  assert.equal(new Set(routes.map(op => op.method + ' ' + op.path)).size, 11);
  for (const op of routes) {
    assert.equal(op.bucket, 'operations', op.path);
    assert.equal(op.method, 'GET', op.path);
    assert.equal(op.dest, '/api/native_roll.rs', op.path);
    assert.equal(op.runtime, 'native-rust', op.path);
    assert.equal(op.status, 'target', op.path);
    assert.equal(op.owning_issue, 4836, op.path);
  }
  for (const route of [
    '/api/v2/creators',
    '/api/v2/creators/{creator_key}',
    '/api/v2/creators/{creator_key}/series/{series_key}/issues',
  ]) {
    liveOperation(fragment, 'GET', route);
  }
  assert.equal(liveOperation(fragment, 'GET', '/api/v1/threads/{thread_id}/issues/creators').dest, '/api/native_roll.rs');
});
