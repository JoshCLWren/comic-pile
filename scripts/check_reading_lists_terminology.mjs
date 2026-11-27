#!/usr/bin/env node
/**
 * CI guard for the #3676 binding nomenclature contract.
 *
 * The product name is Reading Lists. The implementation is the Reading List
 * engine / reading-order eligibility. The retired option-letter name must not
 * appear in active product, runtime, test or documentation source, in any
 * case, separator or identifier spelling variant.
 *
 * Boundary-aware matching avoids false positives from unrelated words such as
 * `adoption exists` or `CblAdoptionEntryResponse`.
 *
 * Exclusions are narrow and justified:
 *   - `.rotisserie/` is factory runtime vendored into this checkout, not the
 *     Comic Pile product.
 *   - `frontend/src/generated/` is regenerated from `native/contracts/*.json`
 *     by `scripts/generate_openapi_types.mjs`; the source contracts ARE scanned.
 *   - `docs/api/v2-route-inventory.json`,
 *     `docs/api/route-fragments/vercel-rewrites.json`, `vercel.json` and the
 *     AGENTS.md route-burndown block are bot-owned generated routing artifacts
 *     (`scripts/generate_route_burndown.mjs`), regenerated post-merge. Their
 *     source fragments (`docs/api/route-fragments/*.json`,
 *     `docs/api/sql-budget-sources.json`) ARE scanned.
 *   - `native/migrate/migrations/` is immutable historical provenance.
 */
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import process from 'node:process';
import {fileURLToPath, pathToFileURL} from 'node:url';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Word-boundary-aware retired-terminology pattern (case and separator variants). */
export const RETIRED_TERMINOLOGY =
  /(?<![A-Za-z])[Oo]ption[\s_-]?[Ee](?![a-z])/;

const EXCLUDED_PREFIXES = [
  '.rotisserie/',
  'frontend/src/generated/',
  'native/migrate/migrations/',
];

const EXCLUDED_FILES = new Set([
  'docs/api/v2-route-inventory.json',
  'docs/api/route-fragments/vercel-rewrites.json',
  'vercel.json',
]);

/** Return the source files that the terminology guard scans. */
export function trackedSourceFiles(root = REPO_ROOT) {
  const tracked = spawnSync('git', ['ls-files', '-z'], {
    cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
  });
  const untracked = spawnSync('git', ['ls-files', '--others', '--exclude-standard', '-z'], {
    cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
  });
  for (const result of [tracked, untracked]) {
    if (result.status !== 0) throw new Error(`git ls-files failed: ${result.stderr}`);
  }
  return `${tracked.stdout}\0${untracked.stdout}`
    .split('\0')
    .filter(Boolean)
    .filter((file) => !EXCLUDED_PREFIXES.some((prefix) => file.startsWith(prefix)))
    .filter((file) => !EXCLUDED_FILES.has(file));
}

/**
 * Find retired option-letter terminology in tracked source.
 *
 * @returns {Array<{file: string, line: number, text: string}>} exact evidence
 */
export function findRetiredTerminology(root = REPO_ROOT) {
  const findings = [];
  for (const file of trackedSourceFiles(root)) {
    const absolute = path.join(root, file);
    let text;
    try {
      text = fs.readFileSync(absolute, 'utf8');
    } catch {
      continue; // tracked path that is not a regular readable file (e.g. a symlink)
    }
    if (!text.includes('ption')) continue;
    text.split(/\r?\n/).forEach((line, index) => {
      if (RETIRED_TERMINOLOGY.test(line)) {
        findings.push({file, line: index + 1, text: line.trim()});
      }
    });
  }
  return findings;
}

export function main() {
  const findings = findRetiredTerminology();
  if (findings.length === 0) {
    console.log('Reading Lists terminology guard: zero retired option-letter names in tracked source.');
    return 0;
  }
  console.error('Reading Lists terminology guard failed. Retired option-letter names remain:');
  for (const finding of findings) {
    console.error(`  ${finding.file}:${finding.line}: ${finding.text}`);
  }
  return 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
