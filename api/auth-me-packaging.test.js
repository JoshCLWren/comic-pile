import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const apiRoot = path.dirname(fileURLToPath(import.meta.url));
const tscBin = path.join(apiRoot, 'node_modules', '.bin', 'tsc');

/**
 * Compile the Vercel auth/me entry the way production does: TypeScript to
 * unbundled ESM, import specifiers left intact. Node then loads the JS.
 * Bundler moduleResolution is intentional — it is what hid the missing
 * `.js` extension from `tsc --noEmit` before this test existed.
 */
async function compileAuthMeEntry() {
  const outDir = await mkdtemp(path.join(tmpdir(), 'auth-me-packaging-'));
  const tsconfigPath = path.join(outDir, 'tsconfig.json');
  await writeFile(
    tsconfigPath,
    JSON.stringify({
      compilerOptions: {
        target: 'ES2022',
        module: 'ESNext',
        moduleResolution: 'bundler',
        esModuleInterop: true,
        skipLibCheck: true,
        strict: true,
        rootDir: apiRoot,
        outDir,
        noEmitOnError: true,
        declaration: false,
        sourceMap: false,
      },
      include: [
        'auth/me.ts',
        'src/auth.ts',
        'src/authService.ts',
        'src/authRepository.ts',
        'src/authTypes.ts',
      ].map((relative) => path.join(apiRoot, relative)),
    }),
  );
  const compiled = spawnSync(tscBin, ['-p', tsconfigPath], {
    encoding: 'utf8',
    cwd: apiRoot,
  });
  assert.equal(
    compiled.status,
    0,
    `unbundled tsc failed:\n${compiled.stdout}\n${compiled.stderr}`,
  );
  await symlink(
    path.join(apiRoot, 'node_modules'),
    path.join(outDir, 'node_modules'),
    'dir',
  );
  return outDir;
}

function createMockResponse() {
  const res = {
    statusCode: 200,
    body: undefined,
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(body) {
      this.body = body;
      return this;
    },
  };
  return res;
}

test('unbundled Node ESM can load the Vercel auth/me function', async (t) => {
  const outDir = await compileAuthMeEntry();
  t.after(async () => {
    await rm(outDir, { recursive: true, force: true });
  });

  process.env.SECRET_KEY = process.env.SECRET_KEY || 'packaging-test-secret';
  process.env.DATABASE_URL =
    process.env.DATABASE_URL || 'postgresql://packaging:packaging@127.0.0.1:5432/packaging';

  const entry = path.join(outDir, 'auth', 'me.js');
  let handler;
  try {
    ({ default: handler } = await import(pathToFileURL(entry).href));
  } catch (error) {
    const code = error && typeof error === 'object' && 'code' in error ? error.code : undefined;
    assert.notEqual(
      code,
      'ERR_MODULE_NOT_FOUND',
      `Vercel Node ESM could not load auth/me imports: ${error instanceof Error ? error.message : error}`,
    );
    throw error;
  }

  const res = createMockResponse();
  await handler({ headers: {} }, res);
  assert.equal(res.statusCode, 401);
  assert.deepEqual(res.body, { error: 'Missing or invalid authorization header' });
});
