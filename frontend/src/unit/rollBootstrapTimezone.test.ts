import { beforeEach, expect, it } from 'vitest'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import { createHttpClientStub } from './httpClientStub'
import { makeRollV2Bootstrap } from './rollV2BootstrapFixture'

const client = createHttpClientStub()
const rollBootstrapApi = createRollBootstrapApi(client)

beforeEach(() => {
  client.get.mockReset().mockResolvedValue(makeRollV2Bootstrap())
})

it('sends a valid browser IANA timezone to the v2 bootstrap endpoint', async () => {
  await rollBootstrapApi.get('America/Chicago')

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap', {
    params: { timezone: 'America/Chicago' },
  })
})

it('keeps the canonical v2 bootstrap path when no timezone is available', async () => {
  await rollBootstrapApi.get()

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
  expect(client.get).toHaveBeenCalledTimes(1)
})

it('treats a blank timezone as absent instead of sending garbage', async () => {
  await rollBootstrapApi.get('')

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})

it('never requests the legacy v1 bootstrap path', async () => {
  await rollBootstrapApi.get('America/Chicago')
  await rollBootstrapApi.get()

  for (const call of client.get.mock.calls) {
    expect(call[0]).not.toBe('/v1/roll/bootstrap')
    expect(call[0]).not.toBe('/roll/bootstrap')
  }
})
