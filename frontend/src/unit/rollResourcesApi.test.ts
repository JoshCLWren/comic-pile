import { describe, expect, it } from 'vitest'
import { createApiClient } from '../services/api'
import { createRollResourcesApi } from '../services/rollResourcesApi'
import { createTransportDouble } from './transportDouble'

function apiWithTransport() {
  const transport = createTransportDouble()
  return { transport, api: createRollResourcesApi(createApiClient(() => transport)) }
}

describe('rollResourcesApi', () => {
  it('reads die state from the scoped native resource', async () => {
    const { transport, api } = apiWithTransport()
    await api.dieState()
    expect(transport.get).toHaveBeenCalledWith('/v2/roll/die-state')
  })

  it('reads eligible issue ids, defaulting to no snoozes', async () => {
    const { transport, api } = apiWithTransport()
    await api.eligibleIssueIds()
    expect(transport.get).toHaveBeenCalledWith('/v2/roll/eligible-issue-ids', {
      params: undefined,
    })
  })

  it('reads eligible issue ids with browser snoozes as one query value', async () => {
    const { transport, api } = apiWithTransport()
    await api.eligibleIssueIds([20, 30])
    expect(transport.get).toHaveBeenCalledWith('/v2/roll/eligible-issue-ids', {
      params: { snoozed: '20,30' },
    })
  })

  it('reads visible issue cards in one bounded batch', async () => {
    const { transport, api } = apiWithTransport()
    await api.issueCards([100, 200])
    expect(transport.post).toHaveBeenCalledWith('/v2/issues/cards', {
      issue_ids: [100, 200],
    })
  })
})
