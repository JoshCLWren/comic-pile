import { describe, expect, it } from 'vitest'

import { createCreatorsApi } from '../services/api-creators'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const creatorsApi = createCreatorsApi(client)

const DETAIL_RESPONSE = {
  summary: {
    canonical_creator_key: 'creator:1672',
    display_name: 'Test Creator',
    normalized_roles: ['writer'],
    average_rating: 4.5,
    ratings_count: 10,
    read_unrated_count: 2,
    upcoming_count: 1,
  },
  coverage: {
    rated_issues_total: 10,
    rated_issues_with_creator_metadata: 10,
    ratings_complete: true,
    read_unrated_issues_total: 2,
    read_unrated_issues_with_metadata: 2,
    read_unrated_complete: true,
    unread_issues_total: 0,
    unread_issues_with_metadata: 0,
    upcoming_complete: true,
  },
  role_stats: [],
  rated_issues: [],
  read_unrated_issues: [],
  upcoming_issues: [],
  next_cursor: null,
  rating_distribution: null,
}

const LIST_RESPONSE = {
  items: [
    {
      canonical_creator_key: 'creator:1672',
      display_name: 'Test Creator',
      normalized_roles: ['writer'],
      average_rating: 4.5,
      ratings_count: 10,
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
  coverage: {
    rated_issues_total: 10,
    rated_issues_with_creator_metadata: 10,
    ratings_complete: true,
    read_unrated_issues_total: 2,
    read_unrated_issues_with_metadata: 2,
    read_unrated_complete: true,
    unread_issues_total: 0,
    unread_issues_with_metadata: 0,
    upcoming_complete: true,
  },
}

describe('creatorsApi', () => {
  describe('getDetail', () => {
    it('requests creator detail with skipAuthRedirect: true', async () => {
      client.get.mockResolvedValue(DETAIL_RESPONSE)

      await expect(
        creatorsApi.getDetail('creator:1672', { limit: 10, offset: 0 }),
      ).resolves.toEqual(DETAIL_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators/creator%3A1672', {
        params: { limit: 10, offset: 0 },
        skipAuthRedirect: true,
      })
    })

    it('requests creator detail with only required params', async () => {
      client.get.mockResolvedValue(DETAIL_RESPONSE)

      await expect(
        creatorsApi.getDetail('creator:1672'),
      ).resolves.toEqual(DETAIL_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators/creator%3A1672', {
        params: {},
        skipAuthRedirect: true,
      })
    })
  })

  describe('getList', () => {
    it('requests creator list with skipAuthRedirect: true', async () => {
      client.get.mockResolvedValue(LIST_RESPONSE)

      await expect(
        creatorsApi.getList({ search: 'test', sort: 'name', limit: 20, offset: 0 }),
      ).resolves.toEqual(LIST_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators', {
        params: { search: 'test', sort: 'name', limit: 20, offset: 0 },
        skipAuthRedirect: true,
      })
    })

    it('requests creator list with search only', async () => {
      client.get.mockResolvedValue(LIST_RESPONSE)

      await expect(
        creatorsApi.getList({ search: 'test' }),
      ).resolves.toEqual(LIST_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators', {
        params: { search: 'test' },
        skipAuthRedirect: true,
      })
    })

    it('requests creator list with no params', async () => {
      client.get.mockResolvedValue(LIST_RESPONSE)

      await expect(
        creatorsApi.getList(),
      ).resolves.toEqual(LIST_RESPONSE)

      expect(client.get).toHaveBeenCalledWith('/v1/creators', {
        params: {},
        skipAuthRedirect: true,
      })
    })
  })
})