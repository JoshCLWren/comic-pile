#!/usr/bin/env node
/**
 * Export ComicPile's client-facing OpenAPI schema deterministically.
 *
 * Node port of scripts/export_openapi_schema.py (#5431). The document is built
 * from three contracts, so no Python runtime is needed. The output is a
 * gitignored build artifact (owner directive 2026-11-19): run
 * `node scripts/generate_api_artifacts.mjs`, never commit it.
 *
 * - native/contracts/python-legacy.openapi.json: frozen snapshot of the
 *   remaining Python-served operations. It only ever shrinks: delete entries
 *   when the matching Python handlers are retired.
 * - native/contracts/same-path-runtime.openapi.json and
 *   native/contracts/v2-runtime.openapi.json: the Rust runtime contracts,
 *   gitignored outputs of `cargo run --example api_contracts`.
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

const HTTP_METHODS = new Set(['get', 'put', 'post', 'patch', 'delete', 'head', 'options', 'trace']);

/**
 * Validate a generated OpenAPI document. Replaces the old byte-comparison
 * against a checked-in copy (owner directive 2026-11-19: generated files are
 * build outputs, never PR-authored) with structural strictness:
 * OpenAPI 3.1, at least one operation, a non-empty operationId per operation
 * that is unique in the document, at least one response per operation, and
 * every `#/components/schemas/<name>` reference resolving.
 *
 * @param {string} name - Artifact label used in error messages.
 * @param {object} document - Parsed OpenAPI document.
 * @returns {string[]} Problems found; empty when the document is valid.
 */
export function openapiDocumentProblems(name, document) {
  const problems = [];
  if (!isObject(document)) return [`${name}: document must be an object`];
  if (!String(document.openapi ?? '').startsWith('3.1')) problems.push(`${name}: openapi version must be 3.1.x`);
  const seen = new Map();
  let operations = 0;
  for (const [p, item] of Object.entries(isObject(document.paths) ? document.paths : {})) {
    for (const [method, operation] of Object.entries(isObject(item) ? item : {})) {
      if (!HTTP_METHODS.has(method)) continue;
      operations += 1;
      const label = `${method.toUpperCase()} ${p}`;
      const id = operation?.operationId;
      if (!isString(id) || id === '') problems.push(`${name}: ${label} has no operationId`);
      else if (seen.has(id)) problems.push(`${name}: operationId ${id} is declared by both ${seen.get(id)} and ${label}`);
      else seen.set(id, label);
      if (!isObject(operation?.responses) || Object.keys(operation.responses).length === 0) {
        problems.push(`${name}: ${label} declares no responses`);
      }
    }
  }
  if (operations === 0) problems.push(`${name}: document declares no operations`);
  const schemas = isObject(document.components?.schemas) ? document.components.schemas : {};
  const unresolved = new Set();
  const walk = (value) => {
    if (Array.isArray(value)) value.forEach(walk);
    else if (isObject(value)) {
      for (const [key, child] of Object.entries(value)) {
        if (key === '$ref' && isString(child)) {
          if (!child.startsWith(SCHEMA_REF_PREFIX) || !Object.hasOwn(schemas, child.slice(SCHEMA_REF_PREFIX.length))) {
            unresolved.add(child);
          }
        } else walk(child);
      }
    }
  };
  walk(document);
  if (unresolved.size) problems.push(`${name}: unresolved schema references: ${[...unresolved].sort().join(', ')}`);
  return problems;
}

export function main(argv = process.argv.slice(2)) {
  let output = DEFAULT_OUTPUT;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--output') output = argv[++i];
    else {
      console.error(`unknown argument: ${argv[i]}`);
      return 2;
    }
  }
  const target = path.resolve(ROOT, output);
  const schema = clientOpenapiSchema();
  const problems = openapiDocumentProblems(output, schema);
  if (problems.length) {
    console.error(`Generated OpenAPI schema is invalid:\n  ${problems.join('\n  ')}`);
    return 1;
  }
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.writeFileSync(target, renderOpenapiSchema(schema), 'utf8');
  console.log(`Wrote deterministic OpenAPI schema: ${output}`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
