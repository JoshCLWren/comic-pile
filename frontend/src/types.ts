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

/** Core API contracts generated from FastAPI's OpenAPI document. */
export type ThreadCreatePayload = components['schemas']['ThreadCreate']
export type ThreadUpdatePayload = components['schemas']['ThreadUpdate']
export type ReactivateThreadPayload = components['schemas']['ReactivateRequest']
export type RatePayload = components['schemas']['RateRequest']
export type OverrideRollPayload = components['schemas']['OverrideRequest']
export type Issue = components['schemas']['IssueResponse']
export type IssueListResponse = components['schemas']['IssueListResponse']
export type Dependency = components['schemas']['DependencyResponse']
export type ThreadDependenciesResponse = components['schemas']['ThreadDependenciesResponse']
export type RollResponse = components['schemas']['RollResponse']
