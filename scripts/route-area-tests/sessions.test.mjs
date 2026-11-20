import assert from 'node:assert/strict';
import {test} from 'node:test';
import {liveFragment, liveOperation} from './helpers.mjs';

test('real session and undo fragments retain native-only supported operations', () => {
  const sessions = liveFragment('sessions');
  const undo = liveFragment('undo');

  // Session details/snapshots moved to the resource-shaped v2 surface; the
  // legacy v1/unversioned single-session and list reads are retired (#4343,
  // #4839). Undo snapshots/restore are served on the native v2 surface.
  const expectedSessions = [
    ['GET', '/api/v2/reading-sessions/{session_id}/details'],
    ['GET', '/api/v2/reading-sessions/{session_id}/snapshots'],
  ];
  const undoExpected = [
    ['GET', '/api/v2/undo/{session_id}/snapshots'],
    ['POST', '/api/v2/undo/{session_id}/snapshots/{snapshot_id}/restore'],
  ];

  assert.equal(sessions.operations.length, expectedSessions.length);
  for (const [method, route] of expectedSessions) {
    const op = liveOperation(sessions, method, route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    assert.equal(op.bucket, 'operations', route);
    assert.ok(op.consumers.includes('frontend/src/services/api-sessions.ts'), route);
  }

  assert.equal(undo.operations.length, undoExpected.length);
  for (const [method, route] of undoExpected) {
    const op = liveOperation(undo, method, route);
    assert.equal(op.bucket, 'operations', route);
    assert.equal(op.dest, '/api/native_roll.rs', route);
    assert.equal(op.runtime, 'native-rust', route);
    assert.equal(op.owning_issue, 4839, route);
  }

  assert.ok(![...sessions.operations, ...undo.operations].some(
    op => op.path.includes('current-session') || op.path.includes('restore-session-start'),
  ));
  assert.ok(!sessions.operations.some(
    op => op.path.startsWith('/api/v1/sessions') || op.path.startsWith('/api/sessions'),
  ));
});
