import type { components } from './generated/openapi'

export * from './types/index'

/**
 * Authenticated user payload generated from the FastAPI OpenAPI contract.
 *
 * Keep the public types barrel on the generated response so backend changes to
 * UserResponse produce a deterministic frontend type diff instead of silently
 * drifting from a handwritten copy.
 */
export type AuthUser = components['schemas']['UserResponse']

/**
 * Authentication token payload generated from the FastAPI OpenAPI contract.
 *
 * Keep the public types barrel on the generated response so backend changes to
 * TokenResponse produce a deterministic frontend type diff instead of silently
 * drifting from a handwritten copy.
 */
export type AuthTokens = components['schemas']['TokenResponse']
