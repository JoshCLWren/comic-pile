import { defaultHttpClient, type HttpClient } from './httpClient'
import type { CreatorTeamChemistryResponse } from '../types/index'

/**
 * Build the creator team-chemistry service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The creator team-chemistry API bound to `client`.
 */
export function createCreatorTeamChemistryApi(client: HttpClient) {
  return {
    getChemistry: () => client.get<CreatorTeamChemistryResponse>('/v1/creators/team-chemistry'),
  }
}

export const creatorTeamChemistryApi = createCreatorTeamChemistryApi(defaultHttpClient())
