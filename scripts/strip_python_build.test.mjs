import assert from 'node:assert/strict';
import {test} from 'node:test';
import {withoutPythonBuild, withoutRetiredIssueFunction} from './strip_python_build.mjs';

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

test('consolidates the retired Issue function into the single Rust function', () => {
  const config = {
    builds: [
      {src: 'api/native_roll.rs', use: '@vercel/rust'},
      {src: 'api/native_issue.rs', use: '@vercel/rust'},
      {src: 'package.json', use: '@vercel/static-build'},
    ],
    routes: [
      {src: '/api/_native_issue/health', methods: ['GET'], dest: '/api/native_issue.rs'},
      {src: '^/api/v2/issues/[0-9]+$', methods: ['PATCH'], dest: '/api/native_issue.rs'},
      {src: '^/api/v2/issues/[0-9]+$', methods: ['PATCH'], dest: '/api/native_roll.rs'},
      {src: '^/api/v2/issues/cards$', methods: ['POST'], dest: '/api/native_issue.rs'},
      {src: '/api(?:/.*)?', dest: '/api/native_roll.rs'},
    ],
  };
  const result = withoutRetiredIssueFunction(config);
  assert.deepEqual(result.builds.map(b => b.src), ['api/native_roll.rs', 'package.json']);
  assert.deepEqual(result.routes, [
    {src: '^/api/v2/issues/[0-9]+$', methods: ['PATCH'], dest: '/api/native_roll.rs'},
    {src: '^/api/v2/issues/cards$', methods: ['POST'], dest: '/api/native_roll.rs'},
    {src: '/api(?:/.*)?', dest: '/api/native_roll.rs'},
  ]);
  assert.equal(JSON.stringify(withoutRetiredIssueFunction(result)), JSON.stringify(result));
  assert.equal(withoutRetiredIssueFunction({builds: [], routes: []}).builds.length, 0);
});
