/**
 * ComicVine mapping health types for the queue surface.
 *
 * These alias the generated API client types so the queue card, its action
 * group, and the shared mapping helpers cannot drift from the contract the
 * paginated queue response actually returns.
 */

import type { components } from '../generated/openapi'

export type ComicVineMappingStatus = components['schemas']['ComicVineMappingStatus']

export type ComicVineMappingHealth = components['schemas']['ComicVineMappingHealth']