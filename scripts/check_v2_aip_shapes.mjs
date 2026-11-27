#!/usr/bin/env node
/**
 * Block newly introduced non-Google-compliant `/api/v2` URL shapes (issue #5720).
 *
 * Route fragments in `docs/api/route-fragments/*.json` are the only contributor
 * editable source for the live v2 ingress; `vercel.json`,
 * `docs/api/v2-route-inventory.json` and
 * `docs/api/route-fragments/vercel-rewrites.json` are generated from them. The
 * guard therefore lints fragments, so a route change is checked in the same PR
 * that introduces it and generated contracts inherit the result.
 *
 * Design contract (Google AIP):
 * - AIP-122: plural lowerCamelCase collection identifiers, so no hyphenated or
 *   underscored path segments (`readingLists`, not `reading-lists`).
 * - AIP-131-135: standard Get/List/Create/PATCH/Delete methods, including PATCH
 *   (with `update_mask`) rather than PUT for partial resource updates.
 * - AIP-136: rare custom methods spelled `POST /api/v2/{resource}:verbNoun`
 *   with a lowerCamelCase verb; the method is the final path segment.
 * - AIP-185: one explicit major version in the path (`/api/v2`).
 *
 * Existing noncompliance is not repaired here. It is recorded in
 * `docs/api/v2-aip-shapes-baseline.json`, one entry per `METHOD path` with the
 * owner issue that will retire it. Any violating operation that is not in that
 * baseline fails the check, so new debt cannot be added silently. A baseline
 * entry that is no longer a violation is reported as stale (not an error) so
 * PRs that remove or rename noncompliant routes are never blocked.
 *
 * Usage:
 *   node scripts/check_v2_aip_shapes.mjs
 *   node scripts/check_v2_aip_shapes.mjs --fragments DIR --baseline FILE
 *   node scripts/check_v2_aip_shapes.mjs --print-baseline
 */
import {readFileSync, readdirSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const V2_PREFIX = '/api/v2';
export const FRAGMENTS_DIR = 'docs/api/route-fragments';
export const INVENTORY_PATH = 'docs/api/v2-route-inventory.json';
export const BASELINE_PATH = 'docs/api/v2-aip-shapes-baseline.json';
/** Generated rewrite artifact: owned by the post-merge regeneration bot. */
export const GENERATED_FRAGMENT = 'vercel-rewrites.json';

/** Methods the API may accept at all. */
const KNOWN_METHODS = new Set(['GET', 'POST', 'PATCH', 'DELETE', 'PUT']);
/** AIP-136 custom methods read with GET or mutate with POST; nothing else. */
const CUSTOM_METHOD_METHODS = new Set(['GET', 'POST']);
/** Bare verbs that belong in `:verbNoun` custom methods, not subpaths. */
const ACTION_VERBS = new Set([
  'activate',
  'apply',
  'approve',
  'archive',
  'cancel',
  'check',
  'compare',
  'confirm',
  'correct',
  'deactivate',
  'delete',
  'detect',
  'dismiss',
  'download',
  'export',
  'import',
  'merge',
  'preview',
  'project',
  'promote',
  'publish',
  'refresh',
  'reject',
  'replace',
  'reset',
  'resolve',
  'restore',
  'retry',
  'revert',
  'search',
  'sync',
  'switch',
  'undo',
  'upload',
  'verify',
]);

const LOWER_CAMEL_CASE = /^[a-z][A-Za-z0-9]*$/;
const REASON_TRAILING_SLASH = 'trailing-slash';
const REASON_EMPTY_PATH = 'empty-resource-path';
const REASON_SEGMENT = 'non-lowercamelcase-segment';
const REASON_ACTION = 'action-shaped-subpath';
const REASON_CUSTOM_NOT_FINAL = 'custom-method-not-final';
const REASON_CUSTOM_MALFORMED = 'custom-method-malformed';
const REASON_CUSTOM_VERB_CASE = 'custom-method-not-lowercamelcase';
const REASON_CUSTOM_METHOD_VERB = 'custom-method-verb';
const REASON_PUT = 'put-mutation';
const REASON_UNKNOWN_METHOD = 'unsupported-verb';

function isParameterSegment(segment) {
  return segment.startsWith('{') && segment.endsWith('}') && segment.length > 2;
}

function staticSegments(apiPath) {
  return apiPath.slice(V2_PREFIX.length).split('/').filter(Boolean);
}

/**
 * Classify one operation against the AIP v2 URL-shape contract.
 *
 * @param {string} method HTTP method as written in the fragment.
 * @param {string} apiPath Absolute request path, e.g. `/api/v2/readingLists/{list_id}`.
 * @returns {string[]} Stable reason codes; empty when the shape conforms.
 */
export function classifyV2Path(method, apiPath) {
  const verb = String(method ?? '').toUpperCase();
  const rawPath = String(apiPath ?? '');
  /** @type {string[]} */
  const reasons = [];

  if (!rawPath.startsWith(V2_PREFIX)) {
    // v1 and unversioned operations are retired through the cutover issues, not
    // through this v2 shape contract.
    return [];
  }
  if (!KNOWN_METHODS.has(verb)) {
    reasons.push(REASON_UNKNOWN_METHOD);
  }
  if (verb === 'PUT') {
    // AIP-134 partial updates are PATCH + update_mask; there is no PUT resource
    // method in the contract this repository targets.
    reasons.push(REASON_PUT);
  }
  if (rawPath === V2_PREFIX || rawPath === `${V2_PREFIX}/`) {
    return [...reasons, REASON_EMPTY_PATH];
  }
  if (rawPath.endsWith('/')) {
    reasons.push(REASON_TRAILING_SLASH);
  }

  const segments = staticSegments(rawPath);
  segments.forEach((segment, index) => {
    if (isParameterSegment(segment)) {
      return;
    }
    const isFinal = index === segments.length - 1;
    if (segment.includes(':')) {
      const parts = segment.split(':');
      if (parts.length !== 2 || parts[0] === '' || parts[1] === '') {
        reasons.push(REASON_CUSTOM_MALFORMED);
        return;
      }
      if (!isFinal) {
        reasons.push(REASON_CUSTOM_NOT_FINAL);
      }
      if (!LOWER_CAMEL_CASE.test(parts[1])) {
        reasons.push(REASON_CUSTOM_VERB_CASE);
      }
      if (!CUSTOM_METHOD_METHODS.has(verb)) {
        reasons.push(REASON_CUSTOM_METHOD_VERB);
      }
      return;
    }
    if (!LOWER_CAMEL_CASE.test(segment)) {
      reasons.push(REASON_SEGMENT);
    }
    if (ACTION_VERBS.has(segment.toLowerCase())) {
      reasons.push(REASON_ACTION);
    }
  });

  return [...new Set(reasons)];
}

/**
 * Read the contributor-editable route fragments.
 *
 * @param {string} fragmentsDirectory Absolute or repo-relative fragments directory.
 * @returns {Array<{method: string, path: string, owning_issue: number|null, source: string}>}
 */
export function loadFragmentOperations(fragmentsDirectory) {
  const fileNames = readdirSync(fragmentsDirectory)
    .filter(name => name.endsWith('.json') && name !== GENERATED_FRAGMENT)
    .sort();
  /** @type {Array<{method: string, path: string, owning_issue: number|null, source: string}>} */
  const operations = [];
  for (const fileName of fileNames) {
    const document = JSON.parse(
      readFileSync(path.join(fragmentsDirectory, fileName), 'utf8'),
    );
    const defaultIssue = document?.defaults?.owning_issue ?? null;
    for (const operation of document?.operations ?? []) {
      operations.push({
        method: String(operation?.method ?? ''),
        path: String(operation?.path ?? ''),
        owning_issue: operation?.owning_issue ?? defaultIssue,
        source: `${FRAGMENTS_DIR}/${fileName}`,
      });
    }
  }
  return operations;
}

/**
 * Read the generated live-operation inventory.
 *
 * A few historical v2 ingress routes are declared directly in `vercel.json` and
 * therefore appear in the generated inventory without a fragment. They are still
 * live operations, so the shape contract covers them.
 *
 * @param {string} inventoryFile Path to `docs/api/v2-route-inventory.json`.
 * @returns {Array<{method: string, path: string, owning_issue: number|null, source: string}>}
 */
export function loadInventoryOperations(inventoryFile) {
  const document = JSON.parse(readFileSync(inventoryFile, 'utf8'));
  return (document?.operations ?? []).map(operation => ({
    method: String(operation?.method ?? ''),
    path: String(operation?.path ?? ''),
    owning_issue: operation?.owning_issue ?? null,
    source: path.basename(inventoryFile),
  }));
}

/**
 * Combine every live-operation source, de-duplicated by `METHOD path`.
 *
 * @param {Array<Array<{method: string, path: string, owning_issue: number|null, source: string}>>} sources
 */
export function mergeOperations(...sources) {
  /** @type {Map<string, {method: string, path: string, owning_issue: number|null, source: string}>} */
  const merged = new Map();
  for (const source of sources) {
    for (const operation of source) {
      const key = `${operation.method.toUpperCase()} ${operation.path}`;
      if (!merged.has(key)) {
        merged.set(key, {...operation, method: operation.method.toUpperCase()});
      }
    }
  }
  return [...merged.values()];
}

/**
 * Parse and validate the accepted-debt baseline.
 *
 * @param {string} baselineFile Path to the baseline JSON file.
 * @returns {Map<string, {method: string, path: string, owning_issue: number, reason: string}>}
 */
export function loadBaseline(baselineFile) {
  const document = JSON.parse(readFileSync(baselineFile, 'utf8'));
  const entries = document?.entries;
  if (!Array.isArray(entries)) {
    throw new Error(`${baselineFile}: expected an "entries" array`);
  }
  /** @type {Map<string, {method: string, path: string, owning_issue: number, reason: string}>} */
  const baseline = new Map();
  entries.forEach((entry, index) => {
    const method = String(entry?.method ?? '').toUpperCase();
    const apiPath = String(entry?.path ?? '');
    const owner = entry?.owning_issue;
    const reason = String(entry?.reason ?? '').trim();
    if (!KNOWN_METHODS.has(method) || !apiPath.startsWith(`${V2_PREFIX}/`)) {
      throw new Error(
        `${baselineFile}: entry ${index} must be a ${V2_PREFIX} METHOD path`,
      );
    }
    if (!Number.isInteger(owner) || owner <= 0) {
      // Every exemption must name the issue that retires it; anonymous
      // exemptions would hide debt instead of tracking it.
      throw new Error(
        `${baselineFile}: entry ${index} (${method} ${apiPath}) needs an owning_issue`,
      );
    }
    if (reason === '') {
      throw new Error(
        `${baselineFile}: entry ${index} (${method} ${apiPath}) needs a reason`,
      );
    }
    const key = `${method} ${apiPath}`;
    if (baseline.has(key)) {
      throw new Error(`${baselineFile}: duplicate entry ${key}`);
    }
    baseline.set(key, {method, path: apiPath, owning_issue: owner, reason});
  });
  return baseline;
}

/**
 * Compare current operations with the accepted-debt baseline.
 *
 * @param {Array<{method: string, path: string, owning_issue: number|null, source: string}>} operations
 * @param {Map<string, {method: string, path: string, owning_issue: number, reason: string}>} baseline
 */
export function evaluateOperations(operations, baseline) {
  /** @type {Array<{method: string, path: string, reasons: string[], owning_issue: number|null, source: string}>} */
  const violations = [];
  const violatingKeys = new Set();
  for (const operation of operations) {
    const method = operation.method.toUpperCase();
    const reasons = classifyV2Path(method, operation.path);
    if (reasons.length === 0) {
      continue;
    }
    violations.push({...operation, method, reasons});
    violatingKeys.add(`${method} ${operation.path}`);
  }
  violations.sort((left, right) =>
    `${left.path} ${left.method}`.localeCompare(`${right.path} ${right.method}`),
  );
  const unexpected = violations.filter(
    violation => !baseline.has(`${violation.method} ${violation.path}`),
  );
  const stale = [...baseline.values()]
    .filter(entry => !violatingKeys.has(`${entry.method} ${entry.path}`))
    .sort((left, right) =>
      `${left.path} ${left.method}`.localeCompare(`${right.path} ${right.method}`),
    );
  return {violations, unexpected, stale};
}

/**
 * Render the baseline that would accept exactly the current violations.
 *
 * @param {Array<{method: string, path: string, reasons: string[], owning_issue: number|null, source: string}>} violations
 * @param {number} fallbackIssue Owner issue for families that name no slice yet.
 */
export function renderBaseline(violations, fallbackIssue) {
  const entries = violations
    .map(violation => ({
      method: violation.method,
      path: violation.path,
      owning_issue: violation.owning_issue ?? fallbackIssue,
      reason: [...violation.reasons].sort().join(','),
    }))
    .sort((left, right) =>
      `${left.path} ${left.method}`.localeCompare(`${right.path} ${right.method}`),
    );
  // One entry per line keeps review diffs to the routes that actually changed.
  const rows = entries.map(entry => `    ${JSON.stringify(entry)}`).join(',\n');
  return `{\n  "schema_version": 1,\n  "description": ${JSON.stringify(
    'Accepted pre-existing noncompliance with the AIP v2 URL-shape contract in'
      + ' docs/api/AIP_V2_SHAPE_GUARD.md. Entries are METHOD path pairs with the'
      + ' issue that retires them. scripts/check_v2_aip_shapes.mjs fails any'
      + ' violation that is not listed here. Remove an entry when its route is'
      + ' renamed or retired.',
  )},\n  "generated_from": "docs/api/route-fragments/*.json + docs/api/v2-route-inventory.json",\n  "entries": [\n${rows}\n  ]\n}\n`;
}

function parseArgs(argv) {
  const options = {
    fragments: FRAGMENTS_DIR,
    inventory: INVENTORY_PATH,
    baseline: BASELINE_PATH,
    printBaseline: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--fragments') {
      options.fragments = argv[index + 1];
      index += 1;
    } else if (argument === '--inventory') {
      options.inventory = argv[index + 1];
      index += 1;
    } else if (argument === '--baseline') {
      options.baseline = argv[index + 1];
      index += 1;
    } else if (argument === '--print-baseline') {
      options.printBaseline = true;
    } else if (argument === '--fallback-issue') {
      options.fallbackIssue = Number(argv[index + 1]);
      index += 1;
    } else if (argument === '--help' || argument === '-h') {
      options.help = true;
    } else {
      throw new Error(`unknown argument: ${argument}`);
    }
  }
  return options;
}

function main(argv) {
  const options = parseArgs(argv);
  if (options.help) {
    console.log(
      'usage: node scripts/check_v2_aip_shapes.mjs [--fragments DIR]'
        + ' [--inventory FILE] [--baseline FILE] [--print-baseline]'
        + ' [--fallback-issue N]',
    );
    return 0;
  }
  const operations = mergeOperations(
    loadFragmentOperations(options.fragments),
    loadInventoryOperations(options.inventory),
  );

  if (options.printBaseline) {
    const {violations} = evaluateOperations(operations, new Map());
    process.stdout.write(renderBaseline(violations, options.fallbackIssue ?? 4456));
    return 0;
  }

  const baseline = loadBaseline(options.baseline);
  const {violations, unexpected, stale} = evaluateOperations(operations, baseline);

  const v2Count = operations.filter(operation =>
    operation.path.startsWith(V2_PREFIX),
  ).length;
  console.log(
    `v2 URL-shape guard: ${v2Count} v2 operations, ${violations.length} accepted`
      + ` noncompliant (baseline ${baseline.size}), ${unexpected.length} new violation(s)`,
  );
  for (const violation of unexpected) {
    console.error(
      `  ${violation.method} ${violation.path} [${violation.reasons.join(',')}]`
        + ` in ${violation.source}`,
    );
  }
  if (unexpected.length > 0) {
    console.error(
      'New /api/v2 operations must follow AIP-122/131-136/185: plural'
        + ' lowerCamelCase collection identifiers, no trailing slash, PATCH'
        + ' instead of PUT, and justified POST :camelCaseVerb custom methods.'
        + ' See docs/api/AIP_V2_SHAPE_GUARD.md.',
    );
    return 1;
  }
  for (const entry of stale) {
    console.log(
      `  note: baseline entry ${entry.method} ${entry.path} is no longer`
        + ' noncompliant; remove it from the baseline.',
    );
  }
  return 0;
}

const invokedDirectly =
  process.argv[1] !== undefined
  && path.resolve(process.argv[1])
    === path.resolve(fileURLToPath(import.meta.url));

if (invokedDirectly) {
  try {
    process.exitCode = main(process.argv.slice(2));
  } catch (error) {
    console.error(`v2 URL-shape guard failed: ${error.message}`);
    process.exitCode = 1;
  }
}
