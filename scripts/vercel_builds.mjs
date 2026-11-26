/**
 * Canonical Vercel function builds for the native-only API.
 *
 * The Python API and the retired second Rust entrypoint no longer exist, so a
 * generated `vercel.json` must always contain exactly these two builds. Both
 * route generators apply this helper, which removes the need for a
 * post-generation strip step and keeps generation order-independent.
 */

export const RUST_BUILD_SRC = 'api/native_api.rs';
export const RUST_DEST = '/api/native_api.rs';
export const STATIC_BUILD_SRC = 'package.json';

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
    const dest = route?.dest;
    if (!dest?.startsWith('/api/')) continue;
    if (dest !== RUST_DEST) {
      throw new Error(`API route ${route.src ?? '<unknown>'} targets retired ingress ${dest}`);
    }
  }
  return document;
}
