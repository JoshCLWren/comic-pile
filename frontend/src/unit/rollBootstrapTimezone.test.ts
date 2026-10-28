import { beforeEach, expect, it } from 'vitest'
import { createRollBootstrapApi } from '../services/rollBootstrapApi'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const rollBootstrapApi = createRollBootstrapApi(client)

beforeEach(() => {
  client.get.mockReset().mockResolvedValue({})
})

it('always requests v2 bootstrap regardless of timezone input', async () => {
  await rollBootstrapApi.get('America/Chicago')

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})

it('keeps the canonical v2 bootstrap path when no timezone is available', async () => {
  await rollBootstrapApi.get()

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
  expect(client.get).toHaveBeenCalledTimes(1)
})

it('treats a blank timezone like any other value and still uses v2', async () => {
  await rollBootstrapApi.get('')

  expect(client.get).toHaveBeenCalledWith('/v2/roll/bootstrap')
})
