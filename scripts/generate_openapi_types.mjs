#!/usr/bin/env node
/**
 * Generate deterministic TypeScript API types from ComicPile's OpenAPI contracts.
 *
 * Node port of scripts/generate_openapi_types.py (#5431). Pipeline: merge the
 * contracts into frontend/src/generated/openapi.json, render openapi.ts with
 * the pinned openapi-typescript, then render the native v2 request client.
 *
 * Every output is a gitignored build artifact (owner directive 2026-11-19:
 * feature PRs never edit or commit generated files). The Rust contracts this
 * reads are produced first by `node scripts/generate_api_artifacts.mjs`, which
 * is the normal entry point and then calls this script.
 */
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {main as exportSchema} from './export_openapi_schema.mjs';
import {CLIENT_OUTPUT, GENERATED_NOTICE, NATIVE_CONTRACT, generateNativeClient} from './generate_native_client.mjs';

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
  // Keep the do-not-edit banner in the generator output itself.
  fs.writeFileSync(output, `${GENERATED_NOTICE}\n${fs.readFileSync(output, 'utf8')}`, 'utf8');
}

export function main(argv = process.argv.slice(2)) {
  let schema = SCHEMA_OUTPUT;
  let output = TYPES_OUTPUT;
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--schema') schema = argv[++i];
    else if (argv[i] === '--output') output = argv[++i];
    else {
      console.error(`unknown argument: ${argv[i]}`);
      return 2;
    }
  }
  const defaultSchema = schema === SCHEMA_OUTPUT;
  const defaultOutputs = defaultSchema && output === TYPES_OUTPUT;

  if (defaultSchema) {
    const code = exportSchema([]);
    if (code !== 0) return code;
  }
  generateTypes(path.resolve(ROOT, schema), path.resolve(ROOT, output));
  console.log(`Generated TypeScript API types with ${GENERATOR_PACKAGE}: ${output}`);
  if (defaultOutputs) {
    generateNativeClient(SCHEMA_OUTPUT, NATIVE_CONTRACT, CLIENT_OUTPUT);
    console.log(`Generated native v2 request client: ${CLIENT_OUTPUT}`);
  }
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
