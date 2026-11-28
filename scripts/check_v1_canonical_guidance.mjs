#!/usr/bin/env node
/**
 * Guard the canonical API guidance against re-instructing new `/api/v1` consumers (#5723).
 *
 * The failure this prevents: `docs/API_V1_CANONICAL.md` once told new client code
 * to call `/api/v1/<family>`, described Python handlers that no longer exist, and
 * cited a contract test that had been deleted. Agents read that file and added new
 * v1 callers.
 *
 * Checks, all deterministic and database-free:
 *
 * 1. Every v1 operation in the all-version live route census is served by native
 *    Rust. A retained v1 path is a compatibility operation, never a surviving Python
 *    handler, and the v2-only inventory count is not v1 retirement proof. The census
 *    is the authoritative source: the bot-owned v2 route inventory is regenerated
 *    after merge, so a contributor PR changing the generator cannot be judged against
 *    a stale generated artifact.
 * 2. `docs/API_V1_CANONICAL.md` states that same live v1 operation count.
 * 3. No active guidance document instructs new code to use v1. Files carrying the
 *    `docs-path-check: historical` marker are archival and are not scanned; the
 *    canonical catalogue itself is always scanned because it is the file that
 *    misdirected agents.
 *
 * Usage: `node scripts/check_v1_canonical_guidance.mjs [--quiet]`
 */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const CENSUS_PATH = 'docs/api/live-route-census.json';
export const CANONICAL_DOC_PATH = 'docs/API_V1_CANONICAL.md';
export const HISTORICAL_MARKER = '<!-- docs-path-check: historical -->';

/** Guidance documents that direct agent and contributor work. */
export const GUIDANCE_DOCS = [
  CANONICAL_DOC_PATH,
  'AGENTS.md',
  'CONTRIBUTING.md',
  'docs/API.md',
  'docs/ARCHITECTURE.md',
  'prompts/agent-next-task.md',
];

/**
 * Imperative patterns that tell a reader to add a new `/api/v1` consumer.
 * Historical prose ("the v1 catalogue is archived"), tests and migration notes are
 * not matched: each pattern requires an instruction verb plus a v1 path.
 */
export const NEW_CONSUMER_PATTERNS = [
  {name: 'must-use-v1', pattern: /\bmust (?:use|call)\b[^.\n]*\/api\/v1\b/i},
  {name: 'new-code-v1', pattern: /\bnew (?:client|frontend|code)\b[^.\n]*\b(?:use|call|target)\b[^.\n]*\/api\/v1\b/i},
  {name: 'canonical-v1-prefix', pattern: /\bcanonical (?:prefix|family|families)\b[^.\n]*\/api\/v1\b/i},
];

const COUNT_STATEMENT = /There are (\d+) retained `\/api\/v1` operations/;

/** Return the retained v1 operations recorded by the all-version live census. */
export function liveV1Operations(census) {
  const routes = census?.routes;
  if (!Array.isArray(routes)) {
    throw new Error(`${CENSUS_PATH}: routes is missing`);
  }
  return routes.filter(route => route?.version === 'v1');
}

/** Return whether a value parsed from JSON is a string, without runtime typeof narrowing. */
function isString(value) {
  return Object.prototype.toString.call(value) === '[object String]';
}

/** Runtime label for an inventory operation, accepting either shape used by the generators. */
export function operationRuntime(operation) {
  const runtime = operation?.runtime ?? operation?.ingress_runtime ?? operation?.ingress;
  return isString(runtime) ? runtime : '';
}

/** Find instructions to add a new v1 consumer in one document body. */
export function findV1Instructions(text) {
  const found = [];
  const lines = text.split('\n');
  for (let index = 0; index < lines.length; index += 1) {
    for (const {name, pattern} of NEW_CONSUMER_PATTERNS) {
      if (pattern.test(lines[index])) {
        found.push({line: index + 1, rule: name, text: lines[index].trim().slice(0, 200)});
      }
    }
  }
  return found;
}

export function checkRepository(root = ROOT) {
  const failures = [];
  const census = JSON.parse(fs.readFileSync(path.join(root, CENSUS_PATH), 'utf8'));
  const operations = liveV1Operations(census);

  for (const operation of operations) {
    const runtime = operationRuntime(operation);
    if (runtime !== 'native-rust') {
      failures.push(
        `${CENSUS_PATH}: ${operation?.method ?? '?'} ${operation?.path ?? '?'} is attributed to `
        + `runtime "${runtime || 'unknown'}"; every retained v1 operation must be native-rust`,
      );
    }
  }

  const canonicalPath = path.join(root, CANONICAL_DOC_PATH);
  const canonicalText = fs.readFileSync(canonicalPath, 'utf8');
  const declared = canonicalText.match(COUNT_STATEMENT);
  if (!declared) {
    failures.push(
      `${CANONICAL_DOC_PATH}: expected the live count sentence `
      + `"There are <n> retained \`/api/v1\` operations"; none found`,
    );
  } else if (Number(declared[1]) !== operations.length) {
    failures.push(
      `${CANONICAL_DOC_PATH}: declares ${declared[1]} retained v1 operations but `
      + `${INVENTORY_PATH} records ${operations.length}`,
    );
  }

  for (const relative of GUIDANCE_DOCS) {
    const absolute = path.join(root, relative);
    if (!fs.existsSync(absolute)) continue;
    const text = fs.readFileSync(absolute, 'utf8');
    const historical = text.includes(HISTORICAL_MARKER) && relative !== CANONICAL_DOC_PATH;
    if (historical) continue;
    for (const finding of findV1Instructions(text)) {
      failures.push(
        `${relative}:${finding.line}: instructs new v1 consumers (${finding.rule}): ${finding.text}`,
      );
    }
  }

  return {operations, failures};
}

export function main(argv = process.argv.slice(2)) {
  const quiet = argv.includes('--quiet');
  let result;
  try {
    result = checkRepository();
  } catch (error) {
    console.error(`v1 canonical guidance guard: ${error.message}`);
    return 1;
  }
  if (result.failures.length > 0) {
    console.error('v1 canonical guidance guard failed:');
    for (const failure of result.failures) console.error(`  - ${failure}`);
    return 1;
  }
  if (!quiet) {
    console.log(
      `v1 canonical guidance guard passed: ${result.operations.length} retained v1 operations, `
      + 'all native-rust, no active guidance instructing new v1 consumers.',
    );
  }
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
