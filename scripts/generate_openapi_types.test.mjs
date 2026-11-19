import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

import {
  FROZEN_CONTRACTS,
  GENERATED_FILES,
  contractCommand,
  isGeneratedArtifactPath,
  main as artifactsMain,
  writtenContracts,
} from './generate_api_artifacts.mjs';

import {
  clientOpenapiSchema,
  isClientSchemaPath,
  mergeNativeRuntimeContract,
  nativeSchemaRenames,
  parseJsonPreservingFloats,
  openapiDocumentProblems,
  renderOpenapiSchema,
} from './export_openapi_schema.mjs';
import {
  GENERATED_NOTICE,
  NativeClientGenerationError,
  methodName,
  renderNativeClient,
  tsType,
} from './generate_native_client.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

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

// Generated artifacts are gitignored build outputs (owner directive
// 2026-11-19), so these tests never compare against a checked-in copy. They
// run the real generator entry point in a staged temporary repository built
// from small fixture contracts and a fake pnpm, so they are deterministic,
// offline, and need no Rust toolchain.
const FIXTURES = path.join(root, 'scripts/__fixtures__/api-artifacts');
const OUTPUTS = [
  'frontend/src/generated/openapi.json',
  'frontend/src/generated/openapi.ts',
  'frontend/src/generated/nativeV2Client.ts',
];

function stageRepo(t, contracts = {}) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'comic-pile-api-artifacts-'));
  t.after(() => fs.rmSync(tmp, {recursive: true, force: true}));
  const staged = (rel) => path.join(tmp, rel);
  fs.mkdirSync(staged('scripts'), {recursive: true});
  for (const name of [
    'export_openapi_schema.mjs',
    'generate_native_client.mjs',
    'generate_openapi_types.mjs',
    'generate_api_artifacts.mjs',
  ]) fs.copyFileSync(path.join(root, 'scripts', name), staged(`scripts/${name}`));
  fs.mkdirSync(staged('native/contracts'), {recursive: true});
  for (const name of ['python-legacy', 'same-path-runtime', 'v2-runtime']) {
    const file = `${name}.openapi.json`;
    const body = contracts[name] ?? fs.readFileSync(path.join(FIXTURES, file), 'utf8');
    fs.writeFileSync(staged(`native/contracts/${file}`), body);
  }
  // Fake pnpm: `pnpm dlx openapi-typescript <schema> --output <out>` writes a
  // deterministic stub derived from the schema bytes.
  const bin = staged('fake-bin');
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'pnpm'), [
    '#!/bin/sh',
    'set -eu',
    '[ "$1" = "dlx" ]',
    '[ "$4" = "--output" ]',
    'printf "export type components = { schemas: Record<string, unknown> }\\n// bytes: %s\\n" "$(wc -c < "$3" | tr -d " ")" > "$5"',
    '',
  ].join('\n'));
  fs.chmodSync(path.join(bin, 'pnpm'), 0o755);
  const run = (script, args = []) => {
    try {
      execFileSync(process.execPath, [staged(`scripts/${script}`), ...args], {
        cwd: tmp,
        env: {...process.env, PATH: bin + path.delimiter + (process.env.PATH ?? '')},
        encoding: 'utf8',
        stdio: 'pipe',
      });
      return 0;
    } catch (error) {
      return error.status;
    }
  };
  const output = (rel) => (fs.existsSync(staged(rel)) ? fs.readFileSync(staged(rel), 'utf8') : null);
  return {run, output, staged};
}

test('generator pipeline writes valid, bannered artifacts byte-identically on every run', (t) => {
  const repo = stageRepo(t);
  assert.equal(repo.run('generate_api_artifacts.mjs', ['--skip-rust']), 0);
  const first = Object.fromEntries(OUTPUTS.map((rel) => [rel, repo.output(rel)]));
  assert.equal(repo.run('generate_openapi_types.mjs'), 0);
  for (const rel of OUTPUTS) {
    assert.notEqual(first[rel], null, `${rel} must be generated`);
    assert.equal(repo.output(rel), first[rel], `${rel} must be deterministic`);
  }
  const schema = parseJsonPreservingFloats(first['frontend/src/generated/openapi.json']);
  assert.deepEqual(openapiDocumentProblems('openapi.json', schema), []);
  assert.deepEqual(Object.keys(schema.paths).sort(), ['/api/v1/legacy', '/api/v1/same', '/api/v2/things', '/health']);
  assert.match(first['frontend/src/generated/openapi.json'], /"minimum": 0\.0/);
  for (const rel of ['frontend/src/generated/openapi.ts', 'frontend/src/generated/nativeV2Client.ts']) {
    assert.ok(first[rel].startsWith(`${GENERATED_NOTICE}\n`), `${rel} must start with the do-not-edit banner`);
  }
  assert.match(first['frontend/src/generated/nativeV2Client.ts'], /listThings\(/);
});

test('generator pipeline refuses an invalid merged schema and writes nothing', (t) => {
  const v2 = JSON.parse(fs.readFileSync(path.join(FIXTURES, 'v2-runtime.openapi.json'), 'utf8'));
  v2.paths['/api/v2/things'].get.operationId = 'get_same';
  const repo = stageRepo(t, {'v2-runtime': JSON.stringify(v2)});
  assert.equal(repo.run('generate_openapi_types.mjs'), 1);
  for (const rel of OUTPUTS) assert.equal(repo.output(rel), null, `${rel} must not be written`);
});

test('generator pipeline fails when a Rust contract has not been generated', (t) => {
  const repo = stageRepo(t);
  fs.rmSync(repo.staged('native/contracts/v2-runtime.openapi.json'));
  assert.notEqual(repo.run('generate_api_artifacts.mjs', ['--skip-rust']), 0);
  for (const rel of OUTPUTS) assert.equal(repo.output(rel), null, `${rel} must not be written`);
  assert.equal(repo.run('generate_openapi_types.mjs', ['--bogus']), 2);
});

test('artifact entry point builds Rust contracts with the locked api_contracts example', () => {
  assert.deepEqual(contractCommand(), [
    'cargo', 'run', '--locked', '--quiet', '-p', 'comicpile-roll-service',
    '--example', 'api_contracts', '--', 'native/contracts',
  ]);
  const error = console.error;
  console.error = () => {};
  try {
    assert.equal(artifactsMain(['--bogus']), 2);
  } finally {
    console.error = error;
  }
});

test('openapiDocumentProblems reports each broken invariant', () => {
  const valid = () => ({
    openapi: '3.1.0',
    paths: {'/api/v2/a': {get: {operationId: 'a', responses: {'200': {content: {'application/json': {schema: {$ref: '#/components/schemas/A'}}}}}}}},
    components: {schemas: {A: {type: 'object'}}},
  });
  assert.deepEqual(openapiDocumentProblems('doc', valid()), []);
  const cases = [
    ['openapi version', (d) => { d.openapi = '3.0.3'; }],
    ['has no operationId', (d) => { delete d.paths['/api/v2/a'].get.operationId; }],
    ['declared by both', (d) => { d.paths['/api/v2/a'].post = structuredClone(d.paths['/api/v2/a'].get); }],
    ['declares no responses', (d) => { d.paths['/api/v2/a'].get.responses = {}; }],
    ['declares no operations', (d) => { d.paths = {}; }],
    ['unresolved schema references', (d) => { d.components.schemas = {}; }],
  ];
  for (const [expected, mutate] of cases) {
    const doc = valid();
    mutate(doc);
    const problems = openapiDocumentProblems('doc', doc);
    assert.ok(problems.some((p) => p.includes(expected)), `${expected}: ${problems.join('; ')}`);
  }
});

test('writtenContracts reads the api_contracts example report', () => {
  assert.deepEqual(
    writtenContracts('wrote native/contracts/v2-runtime.openapi.json\nnoise\nwrote native/contracts/roll-v1.openapi.json\n'),
    ['roll-v1.openapi.json', 'v2-runtime.openapi.json'],
  );
});

test('generated artifacts are gitignored and untracked; frozen contract inputs stay tracked', () => {
  const git = (...args) => execFileSync('git', ['-C', root, ...args], {encoding: 'utf8'});
  const samples = [
    ...GENERATED_FILES,
    'native/contracts/v2-runtime.openapi.json',
    'native/contracts/same-path-runtime.openapi.json',
    // A contract added later is covered by the pattern, not a second registry.
    'native/contracts/some-future-domain-v1.openapi.json',
  ];
  for (const rel of samples) {
    assert.ok(isGeneratedArtifactPath(rel), `${rel} is a generated artifact`);
    assert.doesNotThrow(() => git('check-ignore', '--no-index', '-q', rel), `${rel} must be gitignored`);
    assert.equal(git('ls-files', '--', rel), '', `${rel} must not be tracked`);
  }
  const trackedContracts = git('ls-files', '--', 'native/contracts/*.openapi.json').split('\n').filter(Boolean).sort();
  assert.deepEqual(trackedContracts, [...FROZEN_CONTRACTS].sort());
  for (const rel of FROZEN_CONTRACTS) assert.equal(isGeneratedArtifactPath(rel), false, rel);
  assert.equal(git('ls-files', '--', 'frontend/src/generated'), '');
});
