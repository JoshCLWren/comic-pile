'use strict';

const fs = require('node:fs');
const path = require('node:path');

const SCHEDULED_WORKER_IDS = Object.freeze([1, 2, 3, 4, 5]);

function defaultLockPath() {
  return path.join(__dirname, '..', 'factory-expected-workers.json');
}

function defaultRosterPath() {
  return path.join(__dirname, '..', 'free-model-factories.tsv');
}

function readRosterWorkerIds(rosterPath = defaultRosterPath()) {
  const text = fs.readFileSync(rosterPath, 'utf8');
  const workers = new Set();
  for (const line of text.split(/\r?\n/)) {
    if (!line || line.startsWith('#')) continue;
    const raw = line.split('\t')[0]?.trim();
    if (!raw || !/^\d+$/.test(raw)) continue;
    workers.add(Number(raw));
  }
  return workers;
}

function readLock(lockPath = defaultLockPath()) {
  const payload = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  const expected = new Set(
    Array.isArray(payload.expected_workers)
      ? payload.expected_workers.map(Number).filter(Number.isInteger)
      : [],
  );
  const retired = new Set(
    Array.isArray(payload.retired_workers)
      ? payload.retired_workers.map(Number).filter(Number.isInteger)
      : [],
  );
  return { expected, retired, schemaVersion: payload.schema_version };
}

/**
 * Canonical active fixed-model worker ids.
 * Prefer the lock's expected_workers when present (same rule as factory_roster.expected_workers);
 * otherwise fall back to the live TSV pin list.
 */
function loadExpectedWorkerIds({
  lockPath = defaultLockPath(),
  rosterPath = defaultRosterPath(),
} = {}) {
  const { expected, retired } = readLock(lockPath);
  const rosterWorkers = readRosterWorkerIds(rosterPath);
  const expectedWorkers = expected.size > 0 ? expected : rosterWorkers;
  return {
    expectedWorkers,
    retiredWorkers: retired,
    rosterWorkers,
    scheduledWorkerIds: new Set(SCHEDULED_WORKER_IDS),
  };
}

function isExpectedWorkerId(workerId, loaded = loadExpectedWorkerIds()) {
  return loaded.expectedWorkers.has(Number(workerId));
}

module.exports = {
  SCHEDULED_WORKER_IDS,
  defaultLockPath,
  defaultRosterPath,
  loadExpectedWorkerIds,
  isExpectedWorkerId,
  readRosterWorkerIds,
  readLock,
};
