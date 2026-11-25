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

export const RETIRED_ISSUE_BUILD_SRC = 'api/native_issue.rs';
export const RETIRED_ISSUE_DEST = '/api/native_issue.rs';
export const RETIRED_ISSUE_HEALTH_SRC = '/api/_native_issue/health';

/** Consolidate the retired second Rust function (#5733). The generators
 * preserve baseline natives and `builds` verbatim, so this removes the
 * `api/native_issue.rs` build and every route that targets it (the internal
 * health probe and the two Issue ingress routes). The catch-all already
 * sends those requests to `api/native_roll.rs`, so dropping the routes keeps
 * the output identical to what the generators emit and keeps `--check`
 * stable. Idempotent.
 */
export function withoutRetiredIssueFunction(document) {
  const hasBuild = Array.isArray(document.builds)
    && document.builds.some(build => build.src === RETIRED_ISSUE_BUILD_SRC);
  const hasRoutes = Array.isArray(document.routes)
    && document.routes.some(route => route.dest === RETIRED_ISSUE_DEST
      || route.src === RETIRED_ISSUE_HEALTH_SRC);
  if (!hasBuild && !hasRoutes) return document;
  const result = {...document};
  if (hasBuild) {
    result.builds = document.builds.filter(build => build.src !== RETIRED_ISSUE_BUILD_SRC);
  }
  if (hasRoutes) {
    result.routes = document.routes.filter(route => route.dest !== RETIRED_ISSUE_DEST
      && route.src !== RETIRED_ISSUE_HEALTH_SRC);
  }
  return result;
}

export function withoutPythonBuild(document) {
  if (!Array.isArray(document.builds)) return document;
  const builds = document.builds.filter(build => build.src !== PYTHON_BUILD_SRC);
  if (builds.length === document.builds.length) return document;
  return {...document, builds};
}

export function main(path = 'vercel.json') {
  const original = readFileSync(path, 'utf8');
  const updated = JSON.stringify(withoutRetiredIssueFunction(withoutPythonBuild(JSON.parse(original))), null, 2) + '\n';
  if (updated !== original) {
    writeFileSync(path, updated, 'utf8');
    console.log(`Removed retired function builds/routes from ${path}`);
  } else {
    console.log(`No retired function builds in ${path}`);
  }
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
