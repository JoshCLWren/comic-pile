import assert from 'node:assert/strict';
import {test} from 'node:test';
import {liveFragment, liveOperation} from './helpers.mjs';

test('real taste and bug-report fragments cannot regress to Python ingress', () => {
  const taste = liveFragment('taste-discoveries');
  assert.equal(taste.operations.length, 2);
  liveOperation(taste, 'GET', '/api/v1/taste/discoveries');
  liveOperation(taste, 'POST', '/api/v1/taste/discoveries/{signal_id}/dismiss');
  assert.ok(!taste.operations.some(op => op.method === 'OPTIONS'));
  assert.equal(taste.defaults.runtime, 'native-rust');
  for (const op of taste.operations) assert.equal(op.dest, '/api/native_roll.rs', op.path);

  const bugs = liveFragment('bug-reports');
  assert.deepEqual(
    new Set(bugs.operations.map(op => op.method + ' ' + op.path)),
    new Set(['POST /api/bug-reports/', 'POST /api/v1/bug-reports/']),
  );
  for (const op of bugs.operations) {
    assert.equal(op.dest, '/api/native_roll.rs', op.path);
    assert.equal(op.exclude_from_inventory, true, op.path);
    assert.equal(op.owning_issue, 4852, op.path);
  }
});
