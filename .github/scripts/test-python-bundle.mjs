// Exercise the same glob implementation used by Vercel's Python builder.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const dependencyRoot = process.env.VERCEL_BUILD_UTILS_DIR;
assert.ok(dependencyRoot, 'Set VERCEL_BUILD_UTILS_DIR to the npm installation prefix');
const require = createRequire(path.join(path.resolve(dependencyRoot), 'package.json'));
const { glob } = require('@vercel/build-utils');
const config = JSON.parse(await fs.readFile('vercel.json', 'utf8'));
const pattern = config.builds.find(build => build.src === 'api/index.py').config.excludeFiles;
const sources = [
  'api/index.py', 'app/main.py', 'comic_pile/reading_session.py',
  'Cargo.toml', 'Cargo.lock', 'native/roll-service/Cargo.toml',
  'native/roll-service/Cargo.lock', 'native/roll-service/src/lib.rs',
];
const artifacts = [
  'target/release/deps/native.rlib',
  'target/debug/build/output.o',
  'native/roll-service/target/release/deps/native.rlib',
  'native/roll-service/target/debug/.fingerprint/native.json',
];
const root = await fs.mkdtemp(path.join(os.tmpdir(), 'python-bundle-regression-'));
try {
  for (const file of [...sources, ...artifacts]) {
    const destination = path.join(root, file);
    await fs.mkdir(path.dirname(destination), { recursive: true });
    await fs.writeFile(destination, 'fixture');
  }
  const before = await glob('**', { cwd: root });
  const bundled = await glob('**', { cwd: root, ignore: [pattern] });
  assert.deepEqual(Object.keys(before).sort(), [...sources, ...artifacts].sort());
  assert.deepEqual(Object.keys(bundled).sort(), sources.sort(),
    'Exclude cached root/nested Cargo artifacts while retaining every runtime and build input');
  console.log(`Python bundle regression passed: ${artifacts.length} artifacts excluded, ${sources.length} sources retained`);
} finally {
  await fs.rm(root, { recursive: true, force: true });
}
