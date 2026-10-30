import { beforeEach, expect, it } from 'vitest'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const rollBootstrapApi = createRollBootstrapApi(client)

beforeEach(() => {
  client.get.mockReset().mockResolvedValue({ rollable: [], total_threads: 0, available_threads: 0, excluded_count: 0, excluded_threads: [], inactive_count: 0, inactive_threads: [] })
})

it('sends a valid browser IANA timezone as the bootstrap query parameter', async () => {
  await rollBootstrapApi.get('America/Chicago')

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap', {
    params: { timezone: 'America/Chicago' },
  })
})

it('keeps the canonical bootstrap path when no timezone is available', async () => {
  await rollBootstrapApi.get()

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
  expect(client.get).toHaveBeenCalledTimes(1)
})

it('treats a blank timezone like a missing value instead of sending garbage', async () => {
  await rollBootstrapApi.get('')

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})
