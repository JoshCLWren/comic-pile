#!/usr/bin/env node
/**
 * Export ComicPile's client-facing OpenAPI schema deterministically.
 *
 * Node port of scripts/export_openapi_schema.py (#5431). The document is built
 * from three checked-in contracts, so no Python runtime is needed:
 *
 * - native/contracts/python-legacy.openapi.json: frozen snapshot of the
 *   remaining Python-served operations. It only ever shrinks: delete entries
 *   when the matching Python handlers are retired.
 * - native/contracts/same-path-runtime.openapi.json and
 *   native/contracts/v2-runtime.openapi.json: the Rust runtime contracts.
 *
 * Output is byte-identical to the former `json.dumps(indent=2, sort_keys=True,
 * ensure_ascii=False)` rendering (float literals such as `0.0` are preserved).
 */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const DEFAULT_OUTPUT = 'frontend/src/generated/openapi.json';
export const PYTHON_LEGACY_CONTRACT = path.join(ROOT, 'native/contracts/python-legacy.openapi.json');
export const NATIVE_RUNTIME_CONTRACT = path.join(ROOT, 'native/contracts/v2-runtime.openapi.json');
export const NATIVE_SAME_PATH_CONTRACT = path.join(ROOT, 'native/contracts/same-path-runtime.openapi.json');
const SCHEMA_REF_PREFIX = '#/components/schemas/';
const CLIENT_EXEMPT_BARE_PATHS = new Set(['/api/metrics']);

// JSON floats with a fractional part (`0.0`, `1.5`) would lose their literal
// form through JS numbers. They are carried as marker strings and restored on
// render so the output stays byte-identical to the Python renderer.
const FLOAT_MARK = '\u0000float:';
// Alternation: a whole string literal is consumed first (and left untouched),
// so decimals inside string contents are never rewritten.
const FLOAT_RE = /"(?:[^"\\]|\\.)*"|-?\d+\.\d+(?:[eE][-+]?\d+)?/g;

const isString = (value) => Object.prototype.toString.call(value) === '[object String]';
export const isMarkedFloat = (value) => isString(value) && value.startsWith(FLOAT_MARK);
export const markedFloatText = (value) => value.slice(FLOAT_MARK.length);

export function parseJsonPreservingFloats(text) {
  const marked = text.replace(FLOAT_RE, (m) => (m.startsWith('"') ? m : `"\\u0000float:${m}"`));
  return JSON.parse(marked);
}

export function loadContract(file) {
  return parseJsonPreservingFloats(fs.readFileSync(file, 'utf8'));
}

const isObject = (value) => value !== null && Object.prototype.toString.call(value) === '[object Object]';
const clone = (value) => structuredClone(value);

export function isClientSchemaPath(p) {
  if (!p.startsWith('/api/')) return true;
  if (CLIENT_EXEMPT_BARE_PATHS.has(p)) return true;
  return p === '/api/v1' || p === '/api/v2' || p.startsWith('/api/v1/') || p.startsWith('/api/v2/');
}

export function pruneLegacyBarePaths(schema) {
  const paths = schema.paths;
  if (!isObject(paths)) return schema;
  const pruned = Object.fromEntries(Object.entries(paths).filter(([p]) => isClientSchemaPath(p)));
  if (Object.keys(pruned).length === Object.keys(paths).length) return schema;
  return {...schema, paths: pruned};
}

export function rewriteSchemaRefs(value, renames) {
  if (Array.isArray(value)) return value.map((item) => rewriteSchemaRefs(item, renames));
  if (isObject(value)) {
    const rewritten = Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, rewriteSchemaRefs(v, renames)]),
    );
    const ref = value.$ref;
    if (isString(ref) && ref.startsWith(SCHEMA_REF_PREFIX)) {
      const name = ref.slice(SCHEMA_REF_PREFIX.length);
      if (Object.hasOwn(renames, name)) rewritten.$ref = SCHEMA_REF_PREFIX + renames[name];
    }
    return rewritten;
  }
  return value;
}

function uniqueNativeSchemaName(name, pythonNames, nativeNames, assigned) {
  let candidate = `Native${name}`;
  let suffix = 2;
  while (pythonNames.has(candidate) || nativeNames.has(candidate) || assigned.has(candidate)) {
    candidate = `Native${name}${suffix}`;
    suffix += 1;
  }
  return candidate;
}

export function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (isObject(value)) {
    return Object.fromEntries(
      Object.keys(value).sort().map((k) => [k, sortKeysDeep(value[k])]),
    );
  }
  return value;
}

const canonical = (value) => JSON.stringify(sortKeysDeep(value));

export function nativeSchemaRenames(pythonSchemas, nativeSchemas) {
  const renames = {};
  const nativeNames = new Set(Object.keys(nativeSchemas));
  let changed = true;
  while (changed) {
    changed = false;
    for (const name of Object.keys(nativeSchemas).sort()) {
      if (Object.hasOwn(renames, name) || !Object.hasOwn(pythonSchemas, name)) continue;
      const rewritten = rewriteSchemaRefs(nativeSchemas[name], renames);
      if (canonical(rewritten) === canonical(pythonSchemas[name])) continue;
      renames[name] = uniqueNativeSchemaName(
        name,
        new Set(Object.keys(pythonSchemas)),
        nativeNames,
        new Set(Object.values(renames)),
      );
      changed = true;
    }
  }
  return renames;
}

export function mergeNativeRuntimeContract(schema, native) {
  const pythonSchemas = {...(schema.components?.schemas ?? {})};
  const nativeSchemas = native.components?.schemas ?? {};
  const renames = nativeSchemaRenames(pythonSchemas, nativeSchemas);

  const mergedSchemas = {...pythonSchemas};
  for (const name of Object.keys(nativeSchemas).sort()) {
    const mergedName = Object.hasOwn(renames, name) ? renames[name] : name;
    const rewritten = rewriteSchemaRefs(nativeSchemas[name], renames);
    const existing = mergedSchemas[mergedName];
    if (existing === undefined) {
      mergedSchemas[mergedName] = rewritten;
    } else if (canonical(existing) !== canonical(rewritten)) {
      throw new Error(
        `native schema '${name}' would overwrite Python schema '${mergedName}' with different content`,
      );
    }
  }

  const mergedPaths = clone(schema.paths ?? {});
  for (const [p, operations] of Object.entries(native.paths ?? {})) {
    mergedPaths[p] ??= {};
    for (const [method, operation] of Object.entries(operations)) {
      mergedPaths[p][method] = rewriteSchemaRefs(operation, renames);
    }
  }

  const components = clone(schema.components ?? {});
  components.schemas = mergedSchemas;
  components.securitySchemes ??= {};
  for (const [name, scheme] of Object.entries(native.components?.securitySchemes ?? {})) {
    if (!Object.hasOwn(components.securitySchemes, name)) components.securitySchemes[name] = clone(scheme);
  }
  return {...schema, paths: mergedPaths, components};
}

export function clientOpenapiSchema() {
  const native = mergeNativeRuntimeContract(
    loadContract(NATIVE_SAME_PATH_CONTRACT),
    loadContract(NATIVE_RUNTIME_CONTRACT),
  );
  return pruneLegacyBarePaths(mergeNativeRuntimeContract(loadContract(PYTHON_LEGACY_CONTRACT), native));
}

export function renderOpenapiSchema(schema) {
  const text = JSON.stringify(sortKeysDeep(schema), null, 2);
  const restored = text.replace(/"\\u0000float:([^"]+)"/g, '$1');
  return `${restored}\n`;
}

function simpleDiff(existing, rendered, limit = 90) {
  const a = existing.split('\n');
  const b = rendered.split('\n');
  const out = [];
  for (let i = 0; i < Math.max(a.length, b.length) && out.length < limit; i += 1) {
    if (a[i] === b[i]) continue;
    if (a[i] !== undefined) out.push(`-${i + 1}: ${a[i]}`);
    if (b[i] !== undefined) out.push(`+${i + 1}: ${b[i]}`);
  }
  return out.join('\n');
}

export function main(argv = process.argv.slice(2)) {
  let output = DEFAULT_OUTPUT;
  let check = false;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--check') check = true;
    else if (argv[i] === '--output') output = argv[++i];
    else {
      console.error(`unknown argument: ${argv[i]}`);
      return 2;
    }
  }
  const target = path.resolve(ROOT, output);
  const rendered = renderOpenapiSchema(clientOpenapiSchema());
  if (check) {
    const existing = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : null;
    if (existing === rendered) {
      console.log(`Verified deterministic OpenAPI schema: ${output}`);
      return 0;
    }
    if (existing !== null) console.log(simpleDiff(existing, rendered));
    console.log(
      `Generated OpenAPI schema is stale: ${output}\n` +
        'Run `node scripts/export_openapi_schema.mjs` and commit the result.',
    );
    return 1;
  }
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.writeFileSync(target, rendered, 'utf8');
  console.log(`Wrote deterministic OpenAPI schema: ${output}`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
