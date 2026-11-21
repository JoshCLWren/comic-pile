import assert from 'node:assert/strict';
import {test} from 'node:test';
import {withoutPythonBuild} from './strip_python_build.mjs';

test('removes only the retired Python function build', () => {
  const config = {
    builds: [
      {src: 'api/index.py', use: '@vercel/python', config: {excludeFiles: 'target/**'}},
      {src: 'api/native_roll.rs', use: '@vercel/rust'},
      {src: 'package.json', use: '@vercel/static-build'},
    ],
    routes: [],
  };
  const stripped = withoutPythonBuild(config);
  assert.deepEqual(stripped.builds, config.builds.slice(1));
  assert.equal(config.builds.length, 3);
});

test('leaves configurations without a Python build untouched', () => {
  const config = {builds: [{src: 'api/native_roll.rs', use: '@vercel/rust'}], routes: []};
  assert.equal(withoutPythonBuild(config), config);
  assert.equal(withoutPythonBuild({routes: []}).builds, undefined);
});
