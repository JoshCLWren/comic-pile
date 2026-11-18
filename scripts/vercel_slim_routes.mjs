/**
 * Drop `/api/native_roll.rs` rewrites that the final `/api(?:/.*)?` catch-all
 * already provides.
 *
 * Vercel uses the first matching route. A fragment-derived native_roll route is
 * only REQUIRED when a LATER route (before the catch-all) that points at
 * `/api/index.py` or `/api/native_issue.rs` could also match one of the same
 * method + path pairs. Overlap is decided over a pool of concrete sample paths
 * (every fragment operation path plus a sample derived from every route
 * regex). scripts/generate_route_burndown.py mirrors this algorithm exactly;
 * keep the two in sync.
 */

export const ROLL_DESTINATION = '/api/native_roll.rs';
const CATCH_ALL_SRC = '/api(?:/.*)?';
const TOKEN = /\(\?![^)]*\)|\(\?:\/\.\*\)\?|\[\^\/\]\+|\[0-9\]\+|\.\+|\.\*|\\(.)/g;

function fullMatcher(src) {
  try {
    return new RegExp(`^(?:${src})$`);
  } catch {
    return null;
  }
}

export function sampleFromRegex(src, fill) {
  let body = src;
  if (body.startsWith('^')) body = body.slice(1);
  if (body.endsWith('$')) body = body.slice(0, -1);
  return body.replace(TOKEN, (token, escaped) => {
    if (escaped !== undefined) return escaped;
    if (token === '[0-9]+') return '1';
    if (token === '[^/]+' || token === '.+') return fill;
    return '';
  });
}

export function samplePathsFromTemplates(templates) {
  const out = [];
  for (const template of templates) {
    for (const fill of ['1', 'x']) out.push(template.replace(/\{[^}]+\}/g, fill));
  }
  return out;
}

export function slimNativeRollRoutes(routes, removable, templatePaths) {
  const catchIndex = routes.findIndex(route => route.src === CATCH_ALL_SRC);
  const limit = catchIndex === -1 ? routes.length : catchIndex;
  const matchers = routes.map(route => (typeof route.src === 'string' ? fullMatcher(route.src) : null));
  const pool = new Set(samplePathsFromTemplates(templatePaths));
  routes.forEach((route, index) => {
    if (index >= limit || matchers[index] === null) return;
    for (const fill of ['1', 'x']) {
      const sample = sampleFromRegex(route.src, fill);
      if (matchers[index].test(sample)) pool.add(sample);
    }
  });
  const samples = [...pool].sort();
  const matched = matchers.map((matcher, index) => {
    const hits = new Set();
    if (matcher === null || index >= limit) return hits;
    samples.forEach((sample, sampleIndex) => {
      if (matcher.test(sample)) hits.add(sampleIndex);
    });
    return hits;
  });
  const methodsOverlap = (a, b) => {
    const ma = a.methods || [];
    const mb = b.methods || [];
    if (!ma.length || !mb.length) return true;
    return ma.some(method => mb.includes(method));
  };
  const required = (index) => {
    for (let later = index + 1; later < limit; later++) {
      const other = routes[later];
      if (other.dest === ROLL_DESTINATION) continue;
      if (!methodsOverlap(routes[index], other)) continue;
      for (const hit of matched[index]) {
        if (matched[later].has(hit)) return true;
      }
    }
    return false;
  };
  return routes.filter((route, index) => {
    if (!removable.has(route)) return true;
    if (route.dest !== ROLL_DESTINATION) return true;
    if (matchers[index] === null) return true;
    return required(index);
  });
}
