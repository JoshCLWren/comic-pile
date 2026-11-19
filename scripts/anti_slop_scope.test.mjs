import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function readJson(filePath) {
  return JSON.parse(readFileSync(path.join(repoRoot, filePath), 'utf8'));
}

function readJsonc(filePath) {
  const text = readFileSync(path.join(repoRoot, filePath), 'utf8');
  const withoutComments = text.replace(/\/\/.*$/gm, '');
  const withoutTrailingCommas = withoutComments.replace(/,(\s*[}\]])/g, '$1');
  return JSON.parse(withoutTrailingCommas);
}

test('root and frontend anti-slop scripts resolve to the same repo-wide scope', () => {
  const rootScript = readJson('package.json').scripts['lint:anti-slop'];
  const frontendScript = readJson('frontend/package.json').scripts['lint:anti-slop'];

  assert.equal(
    rootScript.trim(),
    'oxlint -c .oxlintrc.json',
    'root lint:anti-slop must lint the whole repository via the shared config, not a narrowed path',
  );
  assert.equal(
    frontendScript.trim(),
    'cd .. && pnpm run lint:anti-slop',
    'frontend lint:anti-slop must delegate to the root script so both entrypoints share one scope',
  );
});

test('shared anti-slop config excludes .github from the repo-wide gate', () => {
  const config = readJsonc('.oxlintrc.json');
  assert.ok(
    Array.isArray(config.ignorePatterns) && config.ignorePatterns.includes('.github/**'),
    'repo-wide anti-slop gate must exclude .github/** in the shared config',
  );
});
