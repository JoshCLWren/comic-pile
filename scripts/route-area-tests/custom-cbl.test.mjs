import assert from 'node:assert/strict';
import {test} from 'node:test';
import {liveFragment, liveOperation} from './helpers.mjs';

test('real custom CBL source retains native reading-list route ownership', () => {
  const fragment = liveFragment('custom-cbl');
  assert.equal(fragment.operations.length, 15);
  assert.deepEqual(new Set(fragment.operations.map(op => op.bucket)), new Set(['operations']));
  assert.ok(!fragment.operations.some(op => op.method === 'OPTIONS'));
  for (const op of fragment.operations) {
    assert.equal(op.dest, '/api/native_roll.rs', op.path);
    assert.equal(op.runtime, 'native-rust', op.path);
    assert.ok([4684, 4844, 5435].includes(op.owning_issue), op.path + ' owning_issue=' + op.owning_issue);
  }
  for (const [method, route, owningIssue] of [
    ['GET', '/api/v2/reading-lists', 4684],
    ['POST', '/api/v2/reading-lists', 4684],
    ['POST', '/api/v2/reading-lists/memberships:check', 5435],
    ['GET', '/api/v2/reading-lists/{list_id}', 4684],
    ['PUT', '/api/v2/reading-lists/{list_id}', 4684],
    ['DELETE', '/api/v2/reading-lists/{list_id}', 4684],
    ['GET', '/api/v2/reading-lists/{list_id}/reader', 4684],
    ['GET', '/api/v2/reading-lists/issue-candidates', 4844],
    ['GET', '/api/v2/reading-lists/{list_id}/export', 4844],
    ['POST', '/api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/applications', 4844],
    ['GET', '/api/v2/reading-lists/{list_id}/overlap-decisions', 4844],
    ['PUT', '/api/v2/reading-lists/{list_id}/overlap-decisions', 4844],
    ['DELETE', '/api/v2/reading-lists/{list_id}/overlap-decisions/{decision_id}', 4844],
  ]) {
    const op = liveOperation(fragment, method, route);
    assert.equal(op.owning_issue, owningIssue, route);
  }
  for (const [method, route] of [
    ['POST', '/api/v2/reading-lists/{list_id}/adoption-commits'],
    ['POST', '/api/v2/reading-lists/{list_id}/reading-plans/{plan_id}/adoption-commits'],
  ]) {
    const op = liveOperation(fragment, method, route);
    assert.equal(op.owning_issue, 4844, route);
  }
});
