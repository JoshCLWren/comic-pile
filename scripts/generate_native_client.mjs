#!/usr/bin/env node
/**
 * Generate the thin TypeScript request client for deployed native v2 operations.
 *
 * Node port of scripts/generate_native_client.py (#5431); output is
 * byte-identical. The client is derived from native/contracts/v2-runtime.openapi.json
 * (selects the deployed native operations) and frontend/src/generated/openapi.json
 * (merged operation types and component-schema names exported by openapi.ts).
 */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {isMarkedFloat, markedFloatText, parseJsonPreservingFloats} from './export_openapi_schema.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const NATIVE_CONTRACT = 'native/contracts/v2-runtime.openapi.json';
export const UNIFIED_SCHEMA = 'frontend/src/generated/openapi.json';
export const CLIENT_OUTPUT = 'frontend/src/generated/nativeV2Client.ts';

const API_BASE_PREFIX = '/api';
const REF_PREFIX = '#/components/schemas/';
const JSON_MEDIA_TYPE = 'application/json';
const SUPPORTED_METHODS = new Set(['get', 'post', 'put', 'patch', 'delete']);
const IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

export class NativeClientGenerationError extends Error {}

const tag = (v) => Object.prototype.toString.call(v);
const isString = (v) => tag(v) === '[object String]';
const isNumber = (v) => tag(v) === '[object Number]';
const isBoolean = (v) => v === true || v === false;
const isObject = (v) => v !== null && tag(v) === '[object Object]';
const dedupe = (items) => [...new Set(items)];

function obj(value, context) {
  if (!isObject(value)) throw new NativeClientGenerationError(`${context} must be a JSON object`);
  return value;
}

function literal(value) {
  if (isMarkedFloat(value)) return markedFloatText(value);
  if (isString(value)) return JSON.stringify(value);
  if (isBoolean(value)) return value ? 'true' : 'false';
  if (value === null) return 'null';
  if (isNumber(value)) return String(value);
  return 'unknown';
}

function primitiveType(name) {
  const mapping = {
    string: 'string',
    integer: 'number',
    number: 'number',
    boolean: 'boolean',
    null: 'null',
    object: 'Record<string, unknown>',
    array: 'Array<unknown>',
  };
  return Object.hasOwn(mapping, name) ? mapping[name] : 'unknown';
}

const propertyName = (name) => (IDENTIFIER.test(name) ? name : JSON.stringify(name));

function typedSchema(schema, typeName) {
  if (typeName === 'array') {
    if (isObject(schema.items)) return `Array<${tsType(schema.items)}>`;
    return 'Array<unknown>';
  }
  if (typeName === 'object') {
    const properties = schema.properties;
    if (isObject(properties) && Object.keys(properties).length > 0) {
      const required = new Set(Array.isArray(schema.required) ? schema.required.filter(isString) : []);
      const fields = Object.entries(properties).map(
        ([name, prop]) => `${propertyName(name)}${required.has(name) ? '' : '?'}: ${tsType(obj(prop, `property ${name}`))}`,
      );
      return `{ ${fields.join('; ')} }`;
    }
    if (isObject(schema.additionalProperties)) {
      return `Record<string, ${tsType(schema.additionalProperties)}>`;
    }
    return 'Record<string, unknown>';
  }
  return primitiveType(typeName);
}

export function tsType(schema) {
  const ref = schema.$ref;
  if (isString(ref)) {
    if (!ref.startsWith(REF_PREFIX)) throw new NativeClientGenerationError(`unsupported external reference '${ref}'`);
    return `components['schemas']['${ref.slice(REF_PREFIX.length)}']`;
  }
  for (const combinator of ['anyOf', 'oneOf']) {
    if (Array.isArray(schema[combinator])) {
      const unique = dedupe(schema[combinator].map((v) => tsType(obj(v, combinator))));
      return unique.length ? unique.join(' | ') : 'unknown';
    }
  }
  if (Array.isArray(schema.allOf)) {
    const unique = dedupe(schema.allOf.map((v) => tsType(obj(v, 'allOf'))));
    return unique.length ? unique.join(' & ') : 'unknown';
  }
  if ('const' in schema) return literal(schema.const);
  if (Array.isArray(schema.enum) && schema.enum.length) {
    return dedupe(schema.enum.map(literal)).join(' | ');
  }
  const rawType = schema.type;
  if (Array.isArray(rawType)) {
    const unique = dedupe(rawType.filter(isString).map(primitiveType));
    return unique.length ? unique.join(' | ') : 'unknown';
  }
  if (isString(rawType)) return typedSchema(schema, rawType);
  if (isObject(schema.properties)) return typedSchema(schema, 'object');
  if ('items' in schema) return typedSchema(schema, 'array');
  return 'unknown';
}

export function methodName(operationId) {
  const base = operationId.endsWith('_documentation')
    ? operationId.slice(0, -'_documentation'.length)
    : operationId;
  const words = base.split('_').filter(Boolean);
  if (!words.length) throw new NativeClientGenerationError(`operation id '${operationId}' has no usable method name`);
  return words[0] + words.slice(1).map((w) => w.slice(0, 1).toUpperCase() + w.slice(1)).join('');
}

const pascalCase = (name) => name.slice(0, 1).toUpperCase() + name.slice(1);

function successResponseType(operation) {
  const responses = obj(operation.responses, 'responses');
  const codes = Object.keys(responses)
    .filter((c) => /^\d+$/.test(c) && Number(c) >= 200 && Number(c) < 300)
    .map(Number)
    .sort((a, b) => a - b);
  if (!codes.length) return 'void';
  const response = obj(responses[String(codes[0])], 'success response');
  if (!isObject(response.content)) return 'void';
  const jsonContent = response.content[JSON_MEDIA_TYPE];
  if (isObject(jsonContent) && isObject(jsonContent.schema)) {
    return tsType(jsonContent.schema);
  }
  for (const [mediaType, content] of Object.entries(response.content)) {
    if (!isObject(content) || !isObject(content.schema)) continue;
    if (mediaType === 'application/xml' || mediaType.startsWith('text/')) {
      return tsType(content.schema);
    }
  }
  return 'void';
}

function jsonBodySchema(requestBody) {
  const content = obj(requestBody.content, 'requestBody.content');
  if (!isObject(content[JSON_MEDIA_TYPE])) {
    throw new NativeClientGenerationError('request body does not declare application/json content');
  }
  return obj(content[JSON_MEDIA_TYPE].schema, 'requestBody schema');
}

function buildOperation(method, p, operation) {
  if (!SUPPORTED_METHODS.has(method)) throw new NativeClientGenerationError(`unsupported native method '${method}' for ${p}`);
  const operationId = operation.operationId;
  if (!isString(operationId) || !operationId) {
    throw new NativeClientGenerationError(`${method.toUpperCase()} ${p} has no generated operationId`);
  }
  const name = methodName(operationId);
  const pathFields = [];
  const queryFields = [];
  const headerFields = [];
  const pathParameters = [];
  if (Array.isArray(operation.parameters)) {
    for (const raw of operation.parameters) {
      const parameter = obj(raw, 'parameter');
      const pname = parameter.name;
      if (!isString(pname) || !pname) throw new NativeClientGenerationError('parameter has no name');
      const typeText = tsType(obj(parameter.schema ?? {}, 'parameter schema'));
      const required = parameter.required === true;
      if (parameter.in === 'path') {
        pathFields.push([pname, false, typeText]);
        pathParameters.push(pname);
      } else if (parameter.in === 'query') queryFields.push([pname, !required, typeText]);
      else if (parameter.in === 'header') headerFields.push([pname, !required, typeText]);
      else {
        throw new NativeClientGenerationError(`${method.toUpperCase()} ${p} has unsupported parameter location '${parameter.in}'`);
      }
    }
  }
  const fields = [];
  if (pathFields.length) fields.push({name: 'path', optional: false, typeText: null, nested: pathFields});
  if (queryFields.length) fields.push({name: 'query', optional: queryFields.every((f) => f[1]), typeText: null, nested: queryFields});
  if (headerFields.length) fields.push({name: 'header', optional: headerFields.every((f) => f[1]), typeText: null, nested: headerFields});
  let hasBody = false;
  if (isObject(operation.requestBody)) {
    fields.push({
      name: 'body',
      optional: operation.requestBody.required !== true,
      typeText: tsType(jsonBodySchema(operation.requestBody)),
      nested: [],
    });
    hasBody = true;
  }
  return {
    method,
    path: p,
    name,
    requestName: fields.length ? `${pascalCase(name)}Request` : null,
    responseName: `${pascalCase(name)}Response`,
    requestFields: fields,
    responseType: successResponseType(operation),
    pathParameters,
    hasQuery: queryFields.length > 0,
    hasBody,
    hasHeader: headerFields.length > 0,
    hasRequiredInput: fields.some((f) => !f.optional),
  };
}

function nativeOperations(native) {
  const out = new Set();
  for (const [p, item] of Object.entries(obj(native.paths, 'native paths'))) {
    for (const method of Object.keys(obj(item, `native path ${p}`))) out.add(JSON.stringify([method.toLowerCase(), p]));
  }
  return [...out].map((s) => JSON.parse(s)).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
}

function renderRequestType(op) {
  if (op.requestName === null) return [];
  const lines = [`export interface ${op.requestName} {`];
  for (const field of op.requestFields) {
    const optional = field.optional ? '?' : '';
    if (field.typeText !== null) {
      lines.push(`  ${field.name}${optional}: ${field.typeText}`);
      continue;
    }
    lines.push(`  ${field.name}${optional}: {`);
    for (const [n, nestedOptional, typeText] of field.nested) {
      lines.push(`    ${propertyName(n)}${nestedOptional ? '?' : ''}: ${typeText}`);
    }
    lines.push('  }');
  }
  lines.push('}');
  return lines;
}

const pathExpression = (name) => (IDENTIFIER.test(name) ? `args.path.${name}` : `args.path[${JSON.stringify(name)}]`);

function renderUrl(op) {
  if (!op.path.startsWith(`${API_BASE_PREFIX}/`)) {
    throw new NativeClientGenerationError(`native path '${op.path}' is not under ${API_BASE_PREFIX}/`);
  }
  let p = op.path.slice(API_BASE_PREFIX.length);
  if (!op.pathParameters.length) return JSON.stringify(p);
  for (const name of op.pathParameters) {
    p = p.split(`{${name}}`).join(`\${encodeURIComponent(String(${pathExpression(name)}))}`);
  }
  if (/\{[A-Za-z_][A-Za-z0-9_]*\}/.test(p)) {
    throw new NativeClientGenerationError(`native path '${op.path}' has an undeclared path parameter`);
  }
  return `\`${p}\``;
}

function renderCall(op) {
  const url = renderUrl(op);
  const response = op.responseName;
  if (op.method === 'get' || op.method === 'delete') {
    const options = [];
    if (op.hasQuery) options.push('params: compactQuery(args.query)');
    if (op.hasHeader) options.push('headers: args.header');
    if (!options.length) {
      if (!op.pathParameters.length) return [`      return client.${op.method}<${response}>(${url})`];
      return [`      return client.${op.method}<${response}>(`, `        ${url},`, '      )'];
    }
    return [`      return client.${op.method}<${response}>(`, `        ${url},`, `        { ${options.join(', ')} },`, '      )'];
  }
  if (op.hasBody && op.requestName !== null) {
    if (op.hasHeader) {
      return [
        `      return client.${op.method}<${response}, ${op.requestName}['body']>(`,
        `        ${url},`,
        '        args.body,',
        '        { headers: args.header },',
        '      )',
      ];
    }
    return [`      return client.${op.method}<${response}, ${op.requestName}['body']>(`, `        ${url},`, '        args.body,', '      )'];
  }
  if (op.hasHeader) {
    return [`      return client.${op.method}<${response}>(`, `        ${url},`, '        undefined,', '        { headers: args.header },', '      )'];
  }
  return [`      return client.${op.method}<${response}>(${url})`];
}

function renderSignature(op) {
  if (op.requestName === null) return `  ${op.name}(): Promise<${op.responseName}>`;
  return `  ${op.name}(args${op.hasRequiredInput ? '' : '?'}: ${op.requestName}): Promise<${op.responseName}>`;
}

function renderImplementation(op) {
  let head;
  if (op.requestName === null) head = `    ${op.name}() {`;
  else if (op.hasRequiredInput) head = `    ${op.name}(args: ${op.requestName}) {`;
  else head = `    ${op.name}(args: ${op.requestName} = {}) {`;
  return [head, ...renderCall(op), '    },'];
}

export function renderNativeClient(unified, native) {
  const unifiedPaths = obj(unified.paths, 'merged paths');
  const operations = [];
  for (const [method, p] of nativeOperations(native)) {
    const operation = unifiedPaths[p]?.[method];
    if (!isObject(unifiedPaths[p]) || !isObject(operation)) {
      throw new NativeClientGenerationError(`native operation ${method.toUpperCase()} ${p} is missing from the merged generated schema`);
    }
    operations.push(buildOperation(method, p, operation));
  }
  operations.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  const names = operations.map((o) => o.name);
  const duplicates = dedupe(names.filter((n) => names.filter((m) => m === n).length > 1)).sort();
  if (duplicates.length) throw new NativeClientGenerationError(`duplicate generated method names: ${JSON.stringify(duplicates)}`);

  const lines = [
    '// Generated by scripts/generate_native_client.mjs from',
    '// native/contracts/v2-runtime.openapi.json and',
    '// frontend/src/generated/openapi.json. Do not edit by hand.',
    '// Regenerate with `node scripts/generate_openapi_types.mjs`.',
    '',
    "import type { HttpClient } from '../services/httpClient'",
    "import type { components } from './openapi'",
    '',
    '/**',
    ' * Drop absent optional query values before the transport serializes them.',
    ' *',
    ' * @param query - Optional generated query argument group.',
    ' * @returns The present values, or `undefined` when nothing remains.',
    ' */',
    'export function compactQuery(',
    '  query: object | undefined,',
    '): Record<string, unknown> | undefined {',
    '  if (!query) return undefined',
    '  const params: Record<string, unknown> = {}',
    '  for (const [key, value] of Object.entries(query)) {',
    '    if (value !== undefined && value !== null) params[key] = value',
    '  }',
    '  return Object.keys(params).length > 0 ? params : undefined',
    '}',
    '',
  ];
  for (const op of operations) {
    lines.push(...renderRequestType(op));
    if (op.requestName !== null) lines.push('');
    lines.push(`export type ${op.responseName} = ${op.responseType}`, '');
  }
  lines.push('export interface NativeV2Client {');
  lines.push(...operations.map(renderSignature));
  lines.push('}', '', 'export function createNativeV2Client(client: HttpClient): NativeV2Client {', '  return {');
  for (const op of operations) lines.push(...renderImplementation(op));
  lines.push('  }', '}', '');
  return lines.join('\n');
}

const loadJson = (file) => parseJsonPreservingFloats(fs.readFileSync(path.resolve(ROOT, file), 'utf8'));

export function generateNativeClient(schemaPath, nativePath, output) {
  const rendered = renderNativeClient(loadJson(schemaPath), loadJson(nativePath));
  const target = path.resolve(ROOT, output);
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.writeFileSync(target, rendered, 'utf8');
}

export function main(argv = process.argv.slice(2)) {
  const args = {schema: UNIFIED_SCHEMA, native: NATIVE_CONTRACT, output: CLIENT_OUTPUT, check: false};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--check') args.check = true;
    else if (['--schema', '--native', '--output'].includes(argv[i])) args[argv[i].slice(2)] = argv[++i];
    else {
      console.error(`unknown argument: ${argv[i]}`);
      return 2;
    }
  }
  const rendered = renderNativeClient(loadJson(args.schema), loadJson(args.native));
  const target = path.resolve(ROOT, args.output);
  if (args.check) {
    if (fs.existsSync(target) && fs.readFileSync(target, 'utf8') === rendered) {
      console.log(`Verified generated native v2 client: ${args.output}`);
      return 0;
    }
    console.log(`Generated native v2 client is stale: ${args.output}\nRun \`node scripts/generate_openapi_types.mjs\` and commit the result.`);
    return 1;
  }
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.writeFileSync(target, rendered, 'utf8');
  console.log(`Wrote generated native v2 client: ${args.output}`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
