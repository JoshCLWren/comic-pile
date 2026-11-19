import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  clientOpenapiSchema,
  isClientSchemaPath,
  mergeNativeRuntimeContract,
  nativeSchemaRenames,
  parseJsonPreservingFloats,
  main as exportMain,
  renderOpenapiSchema,
} from './export_openapi_schema.mjs';
import {
  NativeClientGenerationError,
  main as clientMain,
  methodName,
  renderNativeClient,
  tsType,
} from './generate_native_client.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(root, rel), 'utf8');

test('checked-in openapi.json is exactly what the contracts render', () => {
  assert.equal(renderOpenapiSchema(clientOpenapiSchema()), read('frontend/src/generated/openapi.json'));
});

test('checked-in native v2 client is exactly what the contracts render', () => {
  const load = (rel) => parseJsonPreservingFloats(read(rel));
  const rendered = renderNativeClient(load('frontend/src/generated/openapi.json'), load('native/contracts/v2-runtime.openapi.json'));
  assert.equal(rendered, read('frontend/src/generated/nativeV2Client.ts'));
});

test('float literals keep their fractional form through render', () => {
  const doc = parseJsonPreservingFloats('{"a": {"minimum": 0.0, "max": 1.5, "n": 3}}');
  assert.equal(renderOpenapiSchema(doc), '{\n  "a": {\n    "max": 1.5,\n    "minimum": 0.0,\n    "n": 3\n  }\n}\n');
});

test('legacy bare /api paths are pruned, versioned and infra paths kept', () => {
  assert.equal(isClientSchemaPath('/api/threads'), false);
  assert.equal(isClientSchemaPath('/api/v1/threads/'), true);
  assert.equal(isClientSchemaPath('/api/v2/roll'), true);
  assert.equal(isClientSchemaPath('/api/metrics'), true);
  assert.equal(isClientSchemaPath('/health'), true);
});

test('native schema colliding with a different legacy schema is renamed, identical is reused', () => {
  const python = {Same: {type: 'string'}, Clash: {type: 'string'}};
  const native = {Same: {type: 'string'}, Clash: {type: 'integer'}};
  assert.deepEqual(nativeSchemaRenames(python, native), {Clash: 'NativeClash'});
  const merged = mergeNativeRuntimeContract(
    {paths: {}, components: {schemas: python}},
    {paths: {'/api/v2/x': {get: {$ref: '#/components/schemas/Clash'}}}, components: {schemas: native}},
  );
  assert.deepEqual(merged.components.schemas.NativeClash, {type: 'integer'});
  assert.equal(merged.paths['/api/v2/x'].get.$ref, '#/components/schemas/NativeClash');
});

test('method names and type rendering', () => {
  assert.equal(methodName('list_threads_documentation'), 'listThreads');
  assert.throws(() => methodName('__'));
  assert.equal(tsType({type: 'array', items: {$ref: '#/components/schemas/Foo'}}), "Array<components['schemas']['Foo']>");
  assert.equal(tsType({anyOf: [{type: 'string'}, {type: 'null'}]}), 'string | null');
});

test('client generator rejects missing merged operations', () => {
  assert.throws(
    () => renderNativeClient(
      {paths: {}, components: {schemas: {}}},
      {paths: {'/api/v2/missing': {get: {operationId: 'get_missing'}}}, components: {schemas: {}}},
    ),
    (err) => err instanceof NativeClientGenerationError
      && err.message.includes('missing from the merged generated schema'),
  );
});

test('client generator rejects duplicate method names', () => {
  const op = (id) => ({operationId: id, responses: {'204': {description: 'ok'}}});
  assert.throws(
    () => renderNativeClient(
      {paths: {'/api/v2/a': {get: op('get_foo')}, '/api/v2/b': {get: op('get_foo_documentation')}}},
      {paths: {'/api/v2/a': {get: {}}, '/api/v2/b': {get: {}}}, components: {schemas: {}}},
    ),
    (err) => err instanceof NativeClientGenerationError
      && err.message.includes('duplicate generated method names')
      && err.message.includes('getFoo'),
  );
});

test('renaming a child schema updates and renames its parent', () => {
  const python = {
    Parent: {type: 'object', properties: {x: {$ref: '#/components/schemas/Child'}}},
    Child: {type: 'string'},
  };
  const native = {
    Parent: {type: 'object', properties: {x: {$ref: '#/components/schemas/Child'}}},
    Child: {type: 'integer'},
  };
  const renames = nativeSchemaRenames(python, native);
  assert.deepEqual(renames, {Child: 'NativeChild', Parent: 'NativeParent'});
  const merged = mergeNativeRuntimeContract(
    {paths: {}, components: {schemas: python}},
    {
      paths: {'/api/v2/x': {get: {responses: {'200': {content: {'application/json': {schema: {$ref: '#/components/schemas/Parent'}}}}}}}},
      components: {schemas: native},
    },
  );
  assert.deepEqual(merged.components.schemas.NativeChild, {type: 'integer'});
  assert.deepEqual(merged.components.schemas.NativeParent, {
    type: 'object',
    properties: {x: {$ref: '#/components/schemas/NativeChild'}},
  });
  assert.equal(
    merged.paths['/api/v2/x'].get.responses['200'].content['application/json'].schema.$ref,
    '#/components/schemas/NativeParent',
  );
});

test('decimals inside JSON strings are not treated as float literals', () => {
  const doc = parseJsonPreservingFloats('{"d": "Examples: 1.5, 2.5, and 3.5", "x": 2.0}');
  assert.equal(doc.d, 'Examples: 1.5, 2.5, and 3.5');
  assert.equal(renderOpenapiSchema(doc), '{\n  "d": "Examples: 1.5, 2.5, and 3.5",\n  "x": 2.0\n}\n');
});

test('export --check fails on a stale schema without rewriting it, and passes when current', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 's5431scr-export-'));
  const out = path.join(tmp, 'openapi.json');
  try {
    fs.writeFileSync(out, '{"stale": true}\n');
    const quiet = (fn) => {
      const log = console.log;
      console.log = () => {};
      try {
        return fn();
      } finally {
        console.log = log;
      }
    };
    assert.equal(quiet(() => exportMain(['--check', '--output', out])), 1);
    assert.equal(fs.readFileSync(out, 'utf8'), '{"stale": true}\n');
    assert.equal(quiet(() => exportMain(['--output', out])), 0);
    assert.equal(fs.readFileSync(out, 'utf8'), read('frontend/src/generated/openapi.json'));
    assert.equal(quiet(() => exportMain(['--check', '--output', out])), 0);
  } finally {
    fs.rmSync(tmp, {recursive: true, force: true});
  }
});

test('native client --check fails on a stale client without rewriting it, and passes when current', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 's5431scr-client-'));
  const out = path.join(tmp, 'nativeV2Client.ts');
  const quiet = (fn) => {
    const log = console.log;
    console.log = () => {};
    try {
      return fn();
    } finally {
      console.log = log;
    }
  };
  try {
    fs.writeFileSync(out, '// stale\n');
    assert.equal(quiet(() => clientMain(['--check', '--output', out])), 1);
    assert.equal(fs.readFileSync(out, 'utf8'), '// stale\n');
    assert.equal(quiet(() => clientMain(['--output', out])), 0);
    assert.equal(fs.readFileSync(out, 'utf8'), read('frontend/src/generated/nativeV2Client.ts'));
    assert.equal(quiet(() => clientMain(['--check', '--output', out])), 0);
  } finally {
    fs.rmSync(tmp, {recursive: true, force: true});
  }
});
