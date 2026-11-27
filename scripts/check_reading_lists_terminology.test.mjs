import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {test} from 'node:test';
import {
  findRetiredTerminology,
  REPO_ROOT,
  RETIRED_TERMINOLOGY,
  trackedSourceFiles,
} from './check_reading_lists_terminology.mjs';

test('boundary-aware pattern matches every retired spelling variant', () => {
  // Built from fragments so this guard never stores the retired name literally.
  for (const text of [
    'Option' + ' E is the evaluator',
    'option' + '_e preview',
    'Option' + 'EProjection',
    'OPTION' + '_E_ENABLED',
    'option' + '-e-queue-test',
    'Option' + '-E off',
  ]) {
    assert.match(text, RETIRED_TERMINOLOGY, text);
  }
});

test('boundary-aware pattern ignores unrelated adoption words', () => {
  for (const text of [
    'once canonical adoption exists',
    'CblAdoptionEntryResponse',
    'large adoption exceeded the timeout',
    'Reading List engine execution_mode is reading_lists',
  ]) {
    assert.doesNotMatch(text, RETIRED_TERMINOLOGY, text);
  }
});

test('tracked source inventory excludes generated and historical provenance', () => {
  const files = trackedSourceFiles(REPO_ROOT);
  assert.ok(files.includes('native/roll-service/src/lib.rs'));
  assert.ok(files.includes('native/contracts/v2-runtime.openapi.json'));
  assert.ok(!files.includes('docs/api/v2-route-inventory.json'));
  assert.ok(!files.some((file) => file.startsWith('frontend/src/generated/')));
  assert.ok(!files.some((file) => file.startsWith('native/migrate/migrations/')));
});

test('guard reports exact file and line evidence for a temporary offender', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'reading-lists-guard-'));
  try {
    // A tiny isolated git repo keeps the fixture out of the real checkout.
    execFileSync('git', ['init', '-q'], {cwd: tmp});
    fs.writeFileSync(path.join(tmp, 'live.rs'), '// ' + 'Option' + ' E' + ' was here\n');
    fs.writeFileSync(path.join(tmp, 'clean.rs'), '// Reading List engine\n');
    execFileSync('git', ['add', '.'], {cwd: tmp});

    const retiredLine = '// ' + 'Option E' + ' was here';
    const findings = findRetiredTerminology(tmp);
    assert.deepEqual(findings, [
      {file: 'live.rs', line: 1, text: retiredLine},
    ]);
  } finally {
    fs.rmSync(tmp, {recursive: true, force: true});
  }
});

test('active repository source has zero retired option-letter terminology', () => {
  assert.deepEqual(findRetiredTerminology(REPO_ROOT), []);
});
