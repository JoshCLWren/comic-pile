#!/usr/bin/env node
/**
 * Generate deterministic TypeScript API types from ComicPile's OpenAPI contracts.
 *
 * Node port of scripts/generate_openapi_types.py (#5431). Pipeline: merge the
 * checked-in contracts into frontend/src/generated/openapi.json, render
 * openapi.ts with the pinned openapi-typescript, then render the native v2
 * request client. `--check` verifies everything is current without writing.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {main as exportSchema} from './export_openapi_schema.mjs';
import {CLIENT_OUTPUT, NATIVE_CONTRACT, generateNativeClient, renderNativeClient} from './generate_native_client.mjs';
import {parseJsonPreservingFloats} from './export_openapi_schema.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SCHEMA_OUTPUT = 'frontend/src/generated/openapi.json';
const TYPES_OUTPUT = 'frontend/src/generated/openapi.ts';
const GENERATOR_PACKAGE = 'openapi-typescript@7.10.1';

export const generatorCommand = (schema, output) => ['pnpm', 'dlx', GENERATOR_PACKAGE, schema, '--output', output];

function generateTypes(schema, output) {
  fs.mkdirSync(path.dirname(output), {recursive: true});
  const [cmd, ...args] = generatorCommand(schema, output);
  const result = spawnSync(cmd, args, {cwd: ROOT, stdio: 'inherit'});
  if (result.status !== 0) throw new Error(`${GENERATOR_PACKAGE} failed (exit ${result.status})`);
}

const sameBytes = (a, b) => fs.existsSync(a) && fs.readFileSync(a).equals(fs.readFileSync(b));

export function main(argv = process.argv.slice(2)) {
  let schema = SCHEMA_OUTPUT;
  let output = TYPES_OUTPUT;
  let check = false;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--check') check = true;
    else if (argv[i] === '--schema') schema = argv[++i];
    else if (argv[i] === '--output') output = argv[++i];
    else {
      console.error(`unknown argument: ${argv[i]}`);
      return 2;
    }
  }
  const defaultSchema = schema === SCHEMA_OUTPUT;
  const defaultOutputs = defaultSchema && output === TYPES_OUTPUT;

  if (defaultSchema) {
    const code = exportSchema(check ? ['--check'] : []);
    if (code !== 0) return code;
  }
  const schemaAbs = path.resolve(ROOT, schema);
  const outputAbs = path.resolve(ROOT, output);

  if (!check) {
    generateTypes(schemaAbs, outputAbs);
    console.log(`Generated TypeScript API types with ${GENERATOR_PACKAGE}: ${output}`);
    if (defaultOutputs) {
      generateNativeClient(SCHEMA_OUTPUT, NATIVE_CONTRACT, CLIENT_OUTPUT);
      console.log(`Generated native v2 request client: ${CLIENT_OUTPUT}`);
    }
    return 0;
  }

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'comic-pile-openapi-'));
  try {
    const generated = path.join(tmp, path.basename(output));
    generateTypes(schemaAbs, generated);
    const typesCurrent = sameBytes(outputAbs, generated);
    let clientCurrent = true;
    if (defaultOutputs) {
      const load = (f) => parseJsonPreservingFloats(fs.readFileSync(path.resolve(ROOT, f), 'utf8'));
      const rendered = renderNativeClient(load(SCHEMA_OUTPUT), load(NATIVE_CONTRACT));
      const clientAbs = path.resolve(ROOT, CLIENT_OUTPUT);
      clientCurrent = fs.existsSync(clientAbs) && fs.readFileSync(clientAbs, 'utf8') === rendered;
    }
    if (typesCurrent && clientCurrent) {
      console.log(`Verified generated TypeScript API types: ${output}`);
      if (defaultOutputs) console.log(`Verified generated native v2 client: ${CLIENT_OUTPUT}`);
      return 0;
    }
  } finally {
    fs.rmSync(tmp, {recursive: true, force: true});
  }
  console.log(
    `Generated TypeScript API artifacts are stale:\n  ${output}\n  ${defaultOutputs ? CLIENT_OUTPUT : 'native v2 client skipped'}\n` +
      'Run `node scripts/generate_openapi_types.mjs` and commit both generated artifacts.',
  );
  return 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
