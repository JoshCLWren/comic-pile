import { beforeEach, describe, expect, it } from 'vitest'

import { createCustomCBLApi } from '../services/api-custom-cbl'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const customCBLApi = createCustomCBLApi(client)

beforeEach(() => {
  client.get.mockReset()
  client.post.mockReset()
  client.put.mockReset()
  client.delete.mockReset()
})

describe('customCBLApi', () => {
  it('lists and loads custom CBLs', async () => {
    const lists = [{ id: 9, name: 'Starman into JSA', description: null, issue_count: 3, updated_at: '2026-09-14T03:00:00Z' }]
    const detail = { ...lists[0], user_id: 1, created_at: lists[0].updated_at, entries: [] }
    client.get.mockResolvedValueOnce(lists).mockResolvedValueOnce(detail)

    await expect(customCBLApi.list()).resolves.toEqual(lists)
    await expect(customCBLApi.get(9)).resolves.toEqual(detail)

    expect(client.get).toHaveBeenNthCalledWith(1, '/v1/custom-cbls')
    expect(client.get).toHaveBeenNthCalledWith(2, '/v1/custom-cbls/9')
  })

  it('creates, updates, and deletes an exact ordered list', async () => {
    const payload = {
      name: 'Starman into JSA',
      description: 'Bridge at #55',
      issue_ids: [26360, 30001, 30002],
    }
    const response = {
      id: 9,
      user_id: 1,
      name: payload.name,
      description: payload.description,
      issue_count: 3,
      created_at: '2026-09-14T03:00:00Z',
      updated_at: '2026-09-14T03:00:00Z',
      entries: [],
    }
    client.post.mockResolvedValueOnce(response)
    client.put.mockResolvedValueOnce(response)
    client.delete.mockResolvedValueOnce(undefined)

    await expect(customCBLApi.create(payload)).resolves.toEqual(response)
    await expect(customCBLApi.update(9, payload)).resolves.toEqual(response)
    await expect(customCBLApi.delete(9)).resolves.toBeUndefined()

    expect(client.post).toHaveBeenCalledWith('/v1/custom-cbls', payload)
    expect(client.put).toHaveBeenCalledWith('/v1/custom-cbls/9', payload)
    expect(client.delete).toHaveBeenCalledWith('/v1/custom-cbls/9')
  })

  it('searches canonical issues with the requested limit', async () => {
    const matches = [
      { issue_id: 26360, thread_id: 180, series_name: 'Starman', issue_number: '55', status: 'unread' },
    ]
    client.get.mockResolvedValueOnce(matches).mockResolvedValueOnce(matches)

    await expect(customCBLApi.searchIssues('Starman')).resolves.toEqual(matches)
    await expect(customCBLApi.searchIssues('Starman', 12)).resolves.toEqual(matches)

    expect(client.get).toHaveBeenNthCalledWith(1, '/v1/custom-cbls/issue-search', {
      params: { q: 'Starman', limit: 30 },
    })
    expect(client.get).toHaveBeenNthCalledWith(2, '/v1/custom-cbls/issue-search', {
      params: { q: 'Starman', limit: 12 },
    })
  })

  it('applies to a Reading Plan with or without an explicit lane', async () => {
    const result = {
      id: 18,
      user_id: 1,
      name: 'Starman + JSA',
      ordering_mode: 'strict_sequential' as const,
      lanes: [{ id: 'main', name: 'Main', order: 0 }],
      nodes: [],
      created_at: '2026-09-14T03:00:00Z',
      updated_at: '2026-09-14T03:05:00Z',
      added_issue_ids: [30001, 30002],
      skipped_existing_issue_ids: [26360],
    }
    client.post.mockResolvedValue(result)

    await expect(customCBLApi.apply(9, 18)).resolves.toEqual(result)
    await expect(customCBLApi.apply(9, 18, 'main')).resolves.toEqual(result)

    expect(client.post).toHaveBeenNthCalledWith(
      1,
      '/v1/custom-cbls/9/reading-plans/18:apply',
      { lane_id: null },
    )
    expect(client.post).toHaveBeenNthCalledWith(
      2,
      '/v1/custom-cbls/9/reading-plans/18:apply',
      { lane_id: 'main' },
    )
  })

  it('exports the list as text XML', async () => {
    const xml = '<ReadingList><Name>Starman into JSA</Name></ReadingList>'
    client.get.mockResolvedValueOnce(xml)

    await expect(customCBLApi.exportXml(9)).resolves.toBe(xml)

    expect(client.get).toHaveBeenCalledWith('/v1/custom-cbls/9/export', {
      responseType: 'text',
    })
  })
})
