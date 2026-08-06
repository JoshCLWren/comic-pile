import type { components } from './generated/openapi'

export * from './types/index'

/**
 * Authentication token payload generated from the FastAPI OpenAPI contract.
 *
 * Keep the public types barrel on the generated response so backend changes to
 * TokenResponse produce a deterministic frontend type diff instead of silently
 * drifting from a handwritten copy.
 */
export type AuthTokens = components['schemas']['TokenResponse']
