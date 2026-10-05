const assert = require('node:assert/strict');
const test = require('node:test');
const {
  loadExpectedWorkerIds,
  isExpectedWorkerId,
  SCHEDULED_WORKER_IDS,
} = require('./factory-expected-workers.cjs');

test('expected workers come from the lock and include post-71 roster pins', () => {
  const { expectedWorkers, retiredWorkers, rosterWorkers } = loadExpectedWorkerIds();
  for (const id of [46, 73, 74, 75, 76]) {
    assert.equal(expectedWorkers.has(id), true, `expected ${id}`);
    assert.equal(isExpectedWorkerId(id), true);
    assert.equal(rosterWorkers.has(id), true);
  }
  assert.equal(expectedWorkers.has(72), false);
  assert.equal(retiredWorkers.has(72), true);
  assert.equal(retiredWorkers.has(71), true);
  assert.equal(isExpectedWorkerId(72), false);
  assert.equal(isExpectedWorkerId(71), false);
  assert.deepEqual([...SCHEDULED_WORKER_IDS], [1, 2, 3, 4, 5]);
});

test('OWNER label definitions track roster size without a hard-coded max', () => {
  const visibility = require('./factory-visibility.cjs');
  const { FIXED_MODEL_OWNER_LABELS, WORKER_OWNER_LABELS, EXPECTED_WORKER_IDS } = visibility._test;
  assert.equal(FIXED_MODEL_OWNER_LABELS.includes('factory:76'), true);
  assert.equal(FIXED_MODEL_OWNER_LABELS.includes('factory:73'), true);
  assert.equal(FIXED_MODEL_OWNER_LABELS.includes('factory:72'), false);
  assert.equal(FIXED_MODEL_OWNER_LABELS.includes('factory:71'), false);
  assert.equal(WORKER_OWNER_LABELS.includes('factory:1'), true);
  assert.equal(WORKER_OWNER_LABELS.includes('factory:5'), true);
  assert.equal(FIXED_MODEL_OWNER_LABELS.length, EXPECTED_WORKER_IDS.size);
  assert.equal(
    WORKER_OWNER_LABELS.length,
    SCHEDULED_WORKER_IDS.length + EXPECTED_WORKER_IDS.size,
  );
});
