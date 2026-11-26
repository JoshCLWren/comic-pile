/**
 * Canonical Vercel function builds for the native-only API.
 *
 * The Python API and the retired second Rust entrypoint no longer exist, so a
 * generated `vercel.json` must always contain exactly these two builds. Both
 * route generators apply this helper, which removes the need for a
 * post-generation strip step and keeps generation order-independent.
 */

export const RUST_BUILD_SRC = 'api/native_roll.rs';
export const RUST_DEST = '/api/native_roll.rs';
export const STATIC_BUILD_SRC = 'package.json';

// The compiled entrypoint is being renamed. Both spellings name the same
// native ingress; the canonical value stays at the deployed spelling until the
// rename actually ships (see #5875).
const NATIVE_DEST_ALIASES = new Set([RUST_DEST, '/api/native_api.rs']);

function isParsedString(value) {
  return Object.prototype.toString.call(value) === '[object String]';
}

/**
 * Normalize a parsed input destination to the one canonical native ingress.
 *
 * This is the single canonicalization at the route-generator input boundary:
 * fragments and previous manifest routes may carry either the legacy or the
 * future spelling, and every generator sees the same canonical destination.
 * Non-native and non-string values pass through unchanged so the existing
 * invariant checks still reject them.
 *
 * Args:
 *   value: Parsed destination value from a fragment or vercel.json route.
 *
 * Returns:
 *   The canonical native destination for either native spelling, otherwise the
 *   original value.
 */
export function canonicalNativeDest(value) {
  return isParsedString(value) && NATIVE_DEST_ALIASES.has(value) ? RUST_DEST : value;
}

export const CANONICAL_BUILDS = [
  {src: RUST_BUILD_SRC, use: '@vercel/rust'},
  {
    src: STATIC_BUILD_SRC,
    use: '@vercel/static-build',
    config: {distDir: 'static/react'},
  },
];

/** Return a document whose builds are the canonical native/static pair. */
export function withCanonicalBuilds(document) {
  return {...document, builds: structuredClone(CANONICAL_BUILDS)};
}

/**
 * Fail closed when a generated or deployed manifest reintroduces a second
 * native function or sends an API request to a retired ingress. This makes the
 * single-entrypoint contract (#5733) an executable build invariant instead of
 * relying on a one-off generated-artifact strip step.
 *
 * Args:
 *   document: Parsed Vercel configuration.
 *
 * Returns:
 *   The same document, unchanged, when the invariant holds.
 *
 * Throws:
 *   Error when the builds or API destinations are not unified.
 */
export function assertSingleNativeIngress(document) {
  const builds = Array.isArray(document.builds) ? document.builds : [];
  const rustBuilds = builds.filter(build => build?.use === '@vercel/rust');
  const staticBuilds = builds.filter(build => build?.src === STATIC_BUILD_SRC);
  if (rustBuilds.length !== 1 || rustBuilds[0].src !== RUST_BUILD_SRC) {
    throw new Error(
      `expected exactly one ${RUST_BUILD_SRC} @vercel/rust build, found `
      + JSON.stringify(rustBuilds.map(build => build.src)),
    );
  }
  if (staticBuilds.length !== 1 || staticBuilds[0].use !== '@vercel/static-build') {
    throw new Error(`expected exactly one ${STATIC_BUILD_SRC} static build`);
  }
  for (const route of Array.isArray(document.routes) ? document.routes : []) {
    const dest = canonicalNativeDest(route?.dest);
    if (!isParsedString(dest) || !dest.startsWith('/api/')) continue;
    if (dest !== RUST_DEST) {
      throw new Error(`API route ${route.src ?? '<unknown>'} targets retired ingress ${dest}`);
    }
  }
  return document;
}
