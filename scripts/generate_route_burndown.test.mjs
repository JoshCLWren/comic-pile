import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {
  copyFileSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {pythonJsonDumps} from './generate_route_burndown.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const nodeScript = path.join(repoRoot, 'scripts', 'generate_route_burndown.mjs');
const fixturesRoot = path.join(repoRoot, 'scripts', '__fixtures__', 'route-burndown');
const fixtureInputs = path.join(fixturesRoot, 'inputs');
const fixtureGolden = path.join(fixturesRoot, 'golden');

const GOLDEN_BY_KEY = {
  inventory: 'inventory.json',
  vercel: 'vercel.json',
  agents: 'AGENTS.md',
  rewrite: 'vercel-rewrites.json',
};

/**
 * Stage the checked-in hermetic fixture inputs into a temp working directory.
 *
 * The generator reads `docs/api/sql-budget-sources.json` relative to cwd, so
 * the staged layout must include that path. Nothing here reads the live
 * `vercel.json`, inventory, AGENTS.md, or route fragments: fragment-only route
 * PRs intentionally leave those bot-owned artifacts stale until post-merge
 * regeneration, so comparing against them would fail every such PR in the
 * `factory-pr-auth` job (which does not regenerate before running these tests).
 *
 * @param {string} tmp Temp directory root.
 * @returns {object} Paths to the staged input/output files and fragments dir.
 */
function stageInputs(tmp) {
  const fragments = path.join(tmp, 'fragments');
  mkdirSync(path.join(tmp, 'docs', 'api'), {recursive: true});
  cpSync(path.join(fixtureInputs, 'fragments'), fragments, {recursive: true});
  for (const file of Object.values(GOLDEN_BY_KEY)) {
    copyFileSync(path.join(fixtureInputs, file), path.join(tmp, file));
  }
  copyFileSync(
    path.join(fixtureInputs, 'sql-budget-sources.json'),
    path.join(tmp, 'docs', 'api', 'sql-budget-sources.json'),
  );
  return {
    inventory: path.join(tmp, 'inventory.json'),
    vercel: path.join(tmp, 'vercel.json'),
    agents: path.join(tmp, 'AGENTS.md'),
    rewrite: path.join(tmp, 'vercel-rewrites.json'),
    fragments,
  };
}

function generatorArgs(files) {
  return [
    '--inventory', files.inventory,
    '--fragments', files.fragments,
    '--rewrite-fragment', files.rewrite,
    '--vercel', files.vercel,
    '--agents', files.agents,
  ];
}

function run(scriptCmd, args, cwd) {
  execFileSync(scriptCmd[0], [...scriptCmd.slice(1), ...args], {cwd, encoding: 'utf8'});
}

function readBytes(filePath) {
  return readFileSync(filePath);
}

test('pythonJsonDumps escapes non-ASCII like Python ensure_ascii=True', () => {
  const text = pythonJsonDumps({s: 'café 😀'});
  assert.ok(text.includes('\\u00e9'), `expected \\u00e9 in ${text}`);
  assert.ok(text.includes('\\ud83d\\ude00'), `expected surrogate pair in ${text}`);
  assert.ok(!text.includes('é'), 'non-ASCII char must be escaped');
  assert.ok(!text.includes('😀'), 'astral char must be escaped');
});

test('node generator matches checked-in golden fixtures on hermetic inputs', (t) => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'route-burndown-golden-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));

  const files = stageInputs(tmp);
  run([process.execPath, nodeScript], generatorArgs(files), tmp);

  for (const [key, golden] of Object.entries(GOLDEN_BY_KEY)) {
    assert.deepEqual(
      readBytes(files[key]),
      readBytes(path.join(fixtureGolden, golden)),
      `${golden} differs from the checked-in golden fixture`,
    );
  }

  // Staleness detection is exercised against fixtures too: a freshly generated
  // tree passes --check, and mutating one output makes it fail with exit 1.
  const checkArgs = [...generatorArgs(files), '--check'];
  run([process.execPath, nodeScript], checkArgs, tmp);
  writeFileSync(files.inventory, `${readFileSync(files.inventory, 'utf8')}\n`);
  assert.throws(() => run([process.execPath, nodeScript], checkArgs, tmp), err => err.status === 1);
});


test('generator rejects invalid fragment input and leaves fixtures untouched', (t) => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'route-burndown-invalid-'));
  t.after(() => rmSync(tmp, {recursive: true, force: true}));

  const files = stageInputs(tmp);
  writeFileSync(
    path.join(files.fragments, 'invalid.json'),
    `${JSON.stringify({
      family: 'invalid',
      owned_path_patterns: ['^/api/v2/bad$'],
      defaults: {},
      operations: [{bucket: 'operations', method: 'GET', path: '/api/v2/bad', dest: '/api/bad'}],
    }, null, 2)}\n`,
  );

  assert.throws(
    () => run([process.execPath, nodeScript], generatorArgs(files), tmp),
    err => err.status === 2,
  );
  assert.deepEqual(
    readBytes(files.inventory),
    readBytes(path.join(fixtureInputs, 'inventory.json')),
    'rejected input must not modify the staged inventory',
  );
});
