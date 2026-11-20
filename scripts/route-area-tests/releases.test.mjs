import assert from 'node:assert/strict';
import {test} from 'node:test';
import {liveFragment, liveOperation} from './helpers.mjs';

test('real releases and dependency fragments retain declared browser routes', () => {
  const releases = liveFragment('releases');
  const expectedReleases = [
    ['GET', '/api/v2/releases'],
    ['PUT', '/api/v1/releases/'],
    ['GET', '/api/v1/releases/source'],
    ['GET', '/api/v1/releases/{release_id}'],
    ['POST', '/api/v1/releases/{release_id}/retract'],
  ];
  assert.equal(releases.operations.length, expectedReleases.length);
  for (const [method, route] of expectedReleases) {
    const op = liveOperation(releases, method, route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    if (route === '/api/v2/releases') {
      assert.equal(op.bucket, 'operations', route);
      assert.ok(op.consumers.includes('frontend/src/services/api-releases.ts'), route);
    } else {
      assert.equal(op.exclude_from_inventory, true, route);
    }
  }
  const dependencies = liveFragment('dependencies');
  assert.deepEqual(new Set(dependencies.operations.map(op => op.bucket)), new Set(['operations', 'v1_operations']));
  for (const [method, route] of [
    ['POST', '/api/v2/dependencies/'],
    ['DELETE', '/api/v2/dependencies/{dependency_id}'],
  ]) {
    const op = liveOperation(dependencies, method, route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    assert.equal(op.runtime, 'native-rust', route);
  }
});
