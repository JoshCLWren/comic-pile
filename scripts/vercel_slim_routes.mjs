/**
 * Drop `/api/native_roll.rs` rewrites that the final `/api(?:/.*)?` catch-all
 * already provides.
 *
 * Vercel uses the first matching route. A fragment-derived native_roll route is
 * only REQUIRED when a LATER route (before the catch-all) that points at
 * `/api/index.py` or `/api/native_issue.rs` could also match the same method +
 * path. Overlap is decided by unifying the two routes segment by segment, so a
 * pair is dropped only when the regexes are PROVEN disjoint. Any regex shape the
 * unifier does not understand (lookaheads, alternation, ...) is treated as
 * overlapping, i.e. the roll route is kept. scripts/generate_route_burndown.mjs
 * mirrors this algorithm exactly; keep the two in sync.
 */

export const ROLL_DESTINATION = '/api/native_roll.rs';
const CATCH_ALL_SRC = '/api(?:/.*)?';
const REGEX_META = new Set(['[', ']', '(', ')', '{', '}', '|', '*', '+', '?', '.', '^', '$']);

/** Parse a route regex into segments, or null when it is not a simple path. */
export function parseSegments(src) {
  let body = src;
  if (body.startsWith('^')) body = body.slice(1);
  if (body.endsWith('$')) body = body.slice(0, -1);
  // `[^/]+` contains a slash; swap it for a sentinel before splitting.
  const parts = body.replaceAll('[^/]+', '\u0001').split('/');
  const segments = [];
  for (let index = 0; index < parts.length; index++) {
    const part = parts[index];
    if (part === '\u0001') {
      segments.push({kind: 'param'});
    } else if (part === '[0-9]+') {
      segments.push({kind: 'num'});
    } else if (part === '.+') {
      if (index !== parts.length - 1) return null;
      segments.push({kind: 'rest'});
    } else {
      let literal = '';
      for (let i = 0; i < part.length; i++) {
        const ch = part[i];
        if (ch === '\\') {
          // Only escaped punctuation is a plain literal; `\d`, `\w`, ... are classes.
          if (i + 1 >= part.length || /[A-Za-z0-9_]/.test(part[i + 1])) return null;
          literal += part[++i];
        } else if (REGEX_META.has(ch)) {
          return null;
        } else {
          literal += ch;
        }
      }
      segments.push({kind: 'lit', value: literal});
    }
  }
  return segments;
}

function segmentsCompatible(a, b) {
  if (a.kind === 'lit' && b.kind === 'lit') return a.value === b.value;
  if (a.kind === 'lit' || b.kind === 'lit') {
    const lit = a.kind === 'lit' ? a : b;
    const other = a.kind === 'lit' ? b : a;
    if (lit.value === '') return false;
    return other.kind !== 'num' || /^[0-9]+$/.test(lit.value);
  }
  return true;
}

/** True when two parsed segment lists can match a common path. */
export function segmentsOverlap(a, b) {
  const count = Math.max(a.length, b.length);
  for (let i = 0; i < count; i++) {
    const left = a[i];
    const right = b[i];
    if ((left && left.kind === 'rest') || (right && right.kind === 'rest')) {
      return left !== undefined && right !== undefined;
    }
    if (left === undefined || right === undefined) return false;
    if (!segmentsCompatible(left, right)) return false;
  }
  return true;
}

function methodsOverlap(a, b) {
  const ma = a.methods || [];
  const mb = b.methods || [];
  if (!ma.length || !mb.length) return true;
  return ma.some(method => mb.includes(method));
}

export function routesMayOverlap(a, b) {
  if (!methodsOverlap(a, b)) return false;
  const left = Object.prototype.toString.call(a.src) === '[object String]' ? parseSegments(a.src) : null;
  const right = Object.prototype.toString.call(b.src) === '[object String]' ? parseSegments(b.src) : null;
  if (left === null || right === null) return true;
  return segmentsOverlap(left, right);
}

export function slimNativeRollRoutes(routes, removable) {
  const catchIndex = routes.findIndex(
    route => route.src === CATCH_ALL_SRC && !(route.methods && route.methods.length),
  );
  const limit = catchIndex === -1 ? routes.length : catchIndex;
  return routes.filter((route, index) => {
    if (!removable.has(route) || route.dest !== ROLL_DESTINATION) return true;
    for (let later = index + 1; later < limit; later++) {
      const other = routes[later];
      if (other.dest === ROLL_DESTINATION) continue;
      if (routesMayOverlap(route, other)) return true;
    }
    return false;
  });
}
