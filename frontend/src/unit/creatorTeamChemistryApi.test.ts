import { describe, expect, it } from 'vitest'

import { createCreatorTeamChemistryApi } from '../services/creatorTeamChemistryApi'
import type { CreatorTeamChemistryResponse } from '../types/index'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const chemistryApi = createCreatorTeamChemistryApi(client)

const RESPONSE: CreatorTeamChemistryResponse = {
  pairs: [],
  pairs_total: 0,
  min_shared_team_sample: 3,
  max_ranked_pairs: 10,
  coverage: {
    rated_issues_total: 0,
    rated_issues_with_creator_metadata: 0,
    ratings_complete: true,
  },
}

describe('creatorTeamChemistryApi', () => {
  it('requests the bounded team-chemistry contract without parameters', async () => {
    client.get.mockResolvedValue(RESPONSE)

    await expect(chemistryApi.getChemistry()).resolves.toEqual(RESPONSE)
    expect(client.get).toHaveBeenCalledWith('/v1/creators/team-chemistry')
  })

  it('exposes a single read method so team chemistry cannot persist', () => {
    expect(Object.keys(chemistryApi)).toEqual(['getChemistry'])
  })
})
