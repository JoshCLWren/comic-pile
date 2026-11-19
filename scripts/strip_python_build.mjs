#!/usr/bin/env node
/** Remove the retired @vercel/python function build from vercel.json.
 *
 * The Python API (`api/index.py`) is deleted; leaving its `builds` entry would
 * make Vercel try to build a function whose source no longer exists. The route
 * generators preserve the `builds` array verbatim, so this narrow post-generation
 * step removes only the Python entry. It runs in regenerate-routes.yml after
 * the deterministic generator checks have passed.
 */
import {readFileSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

export const PYTHON_BUILD_SRC = 'api/index.py';

export function withoutPythonBuild(document) {
  if (!Array.isArray(document.builds)) return document;
  const builds = document.builds.filter(build => build.src !== PYTHON_BUILD_SRC);
  if (builds.length === document.builds.length) return document;
  return {...document, builds};
}

export function main(path = 'vercel.json') {
  const original = readFileSync(path, 'utf8');
  const updated = JSON.stringify(withoutPythonBuild(JSON.parse(original)), null, 2) + '\n';
  if (updated !== original) {
    writeFileSync(path, updated, 'utf8');
    console.log(`Removed the retired ${PYTHON_BUILD_SRC} build from ${path}`);
  } else {
    console.log(`No Python build in ${path}`);
  }
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
