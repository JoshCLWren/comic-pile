/**
 * Canonical Vercel function builds for the native-only API.
 *
 * The Python API and the retired second Rust entrypoint no longer exist, so a
 * generated `vercel.json` must always contain exactly these two builds. Both
 * route generators apply this helper, which removes the need for a
 * post-generation strip step and keeps generation order-independent.
 */

export const CANONICAL_BUILDS = [
  {src: 'api/native_api.rs', use: '@vercel/rust'},
  {
    src: 'package.json',
    use: '@vercel/static-build',
    config: {distDir: 'static/react'},
  },
];

/** Return a document whose builds are the canonical native/static pair. */
export function withCanonicalBuilds(document) {
  return {...document, builds: structuredClone(CANONICAL_BUILDS)};
}
