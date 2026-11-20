#!/usr/bin/env node
/**
 * Guard bot-owned generated files (owner directive 2026-11-19: parallel PRs
 * must not share conflict-causing files).
 *
 * Ordinary pull requests may not edit any file listed in BOT_OWNED_PATHS or
 * the generated route-burndown block of AGENTS.md. These are regenerated from
 * source after merge by .github/workflows/regenerate-routes.yml and committed
 * through the automation/route-regeneration/current bot PR:
 *
 * - route outputs: vercel.json, docs/api/v2-route-inventory.json,
 *   docs/api/route-fragments/vercel-rewrites.json, AGENTS.md burndown block;
 * - API contracts: native/contracts/{v2-runtime,same-path-runtime}.openapi.json
 *   and frontend/src/generated/{openapi.json,openapi.ts,nativeV2Client.ts}.
 *   CI regenerates these from the PR's own Rust code (scripts/generate_contracts.sh)
 *   for every frontend job, so feature PRs never need to commit them.
 *
 * `--allow-generated` is the inverse check for the bot PR: it may change only
 * bot-owned files, and AGENTS.md only inside the generated block.
 *
 * Usage: node scripts/check_generated_files_guard.mjs [--allow-generated]
 *          [--base <rev>] [--head <rev>]
 */
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

export const BOT_OWNED_PATHS = new Set([
  'vercel.json',
  'docs/api/v2-route-inventory.json',
  'docs/api/route-fragments/vercel-rewrites.json',
  'native/contracts/v2-runtime.openapi.json',
  'native/contracts/same-path-runtime.openapi.json',
  'frontend/src/generated/openapi.json',
  'frontend/src/generated/openapi.ts',
  'frontend/src/generated/nativeV2Client.ts',
]);
export const AGENTS_PATH = 'AGENTS.md';
const AGENTS_BEGIN_PREFIX = '<!-- route-burndown:begin';
const AGENTS_END_MARKER = '<!-- route-burndown:end -->';

/** The generated AGENTS.md block including both markers, or null. */
export function extractAgentsBlock(text) {
  const begin = text.indexOf(AGENTS_BEGIN_PREFIX);
  const end = text.indexOf(AGENTS_END_MARKER);
  if (begin === -1 || end === -1 || begin >= end) return null;
  return text.slice(begin, end + AGENTS_END_MARKER.length);
}

/** Whether the generated block differs between two AGENTS.md texts. */
export function agentsBlockChanged(baseText, headText) {
  return extractAgentsBlock(baseText) !== extractAgentsBlock(headText);
}

/** Whether every AGENTS.md change stays inside the generated block. */
export function agentsChangedOnlyInBlock(baseText, headText) {
  const base = extractAgentsBlock(baseText);
  const head = extractAgentsBlock(headText);
  if (base === null || head === null) return false;
  return baseText.replace(base, '') === headText.replace(head, '');
}

/** Violations for an ordinary PR: any bot-owned file it changed. */
export function featurePrViolations(changedFiles, agents) {
  const violations = changedFiles.filter(file => BOT_OWNED_PATHS.has(file)).sort();
  if (changedFiles.includes(AGENTS_PATH) && agents && agentsBlockChanged(agents.base, agents.head)) {
    violations.push(`${AGENTS_PATH} (route-burndown block)`);
  }
  return violations;
}

/** Violations for the bot regeneration PR: anything that is not generated. */
export function botPrViolations(changedFiles, agents) {
  const violations = changedFiles
    .filter(file => !BOT_OWNED_PATHS.has(file) && file !== AGENTS_PATH)
    .sort();
  if (changedFiles.length === 0) violations.push('regeneration PR has no changed artifacts');
  if (changedFiles.includes(AGENTS_PATH) && agents && !agentsChangedOnlyInBlock(agents.base, agents.head)) {
    violations.push(`${AGENTS_PATH} (changes outside route-burndown block)`);
  }
  return violations;
}

const git = (...args) => execFileSync('git', args, {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024});

export function main(argv = process.argv.slice(2)) {
  let base = 'origin/main';
  let head = 'HEAD';
  let allowGenerated = false;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--allow-generated') allowGenerated = true;
    else if (argv[i] === '--base') base = argv[++i];
    else if (argv[i] === '--head') head = argv[++i];
    else {
      console.error(`unknown argument: ${argv[i]}`);
      return 2;
    }
  }
  const changed = git('diff', '--name-only', `${base}...${head}`)
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean);
  let agents = null;
  if (changed.includes(AGENTS_PATH)) {
    const mergeBase = git('merge-base', base, head).trim();
    agents = {base: git('show', `${mergeBase}:${AGENTS_PATH}`), head: git('show', `${head}:${AGENTS_PATH}`)};
  }
  if (allowGenerated) {
    const violations = botPrViolations(changed, agents);
    if (violations.length) {
      console.log('::error::Regeneration PR contains non-generated changes.');
      for (const violation of violations) console.log(`  - ${violation}`);
      return 1;
    }
    console.log('Regeneration PR scope passed; CI verifies the files match the code.');
    return 0;
  }
  const violations = featurePrViolations(changed, agents);
  if (violations.length) {
    console.log('::error::This PR edits bot-owned generated files. Revert them; the route-regeneration bot PR');
    console.log('commits them after merge, and CI regenerates them from your code for every check.');
    console.log('See AGENTS.md "Adding or migrating a route".');
    for (const violation of violations) console.log(`  - ${violation}`);
    return 1;
  }
  console.log('No bot-owned generated files changed.');
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exit(main());
