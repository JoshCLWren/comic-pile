import { beforeEach, expect, it } from 'vitest'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const rollBootstrapApi = createRollBootstrapApi(client)

beforeEach(() => {
  client.post.mockReset().mockResolvedValue({ session_id: 1, created: false })
  client.get.mockReset().mockResolvedValue({ rollable: [], pool_reason: 'no_series' })
})

it('sends a valid browser IANA timezone as the bootstrap query parameter', async () => {
  await rollBootstrapApi.get('America/Chicago')

  expect(client.post).toHaveBeenCalledWith('/v2/reading-sessions', { timezone: 'America/Chicago' })
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap', {
    params: { timezone: 'America/Chicago' },
  })
})

it('keeps the canonical bootstrap path when no timezone is available', async () => {
  await rollBootstrapApi.get()

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
  expect(client.get).toHaveBeenCalledTimes(1)
  expect(client.post).toHaveBeenCalledWith('/v2/reading-sessions', {})
})

it('treats a blank timezone like a missing value instead of sending garbage', async () => {
  await rollBootstrapApi.get('')

  expect(client.post).toHaveBeenCalledWith('/v2/reading-sessions', {})
  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})


it('does not read bootstrap when explicit initialization fails', async () => {
  client.post.mockRejectedValueOnce(new Error('session init unavailable'))
  await expect(rollBootstrapApi.get()).rejects.toThrow('session init unavailable')
  expect(client.get).not.toHaveBeenCalled()
})
