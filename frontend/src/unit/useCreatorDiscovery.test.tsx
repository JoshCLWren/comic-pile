import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDiscovery, useDiscoveryModes } from '../hooks/useCreatorDiscovery'
import { creatorsApi } from '../services/api-creators'
import type { DiscoveryModesResponse, DiscoveryResponse } from '../services/api-creators'

vi.mock('../services/api-creators', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-creators')>()
  return {
    ...actual,
    creatorsApi: {
      ...actual.creatorsApi,
      getDiscoveryModes: vi.fn(),
      getDiscovery: vi.fn(),
    },
  }
})

const mockedModes = vi.mocked(creatorsApi.getDiscoveryModes)
const mockedDiscovery = vi.mocked(creatorsApi.getDiscovery)

const MODES_RESPONSE: DiscoveryModesResponse = {
  modes: [
    {
      mode: 'consistently_loved',
      title: 'Most Consistently Loved',
      description: 'High average with consistent ratings',
    },
  ],
}

const DISCOVERY_RESPONSE: DiscoveryResponse = {
  mode: 'consistently_loved',
  title: 'Most Consistently Loved',
  description: 'High average with consistent ratings',
  items: [],
  total: 0,
  limit: 20,
  offset: 0,
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useCreatorDiscovery', () => {
  it('loads the bounded discovery mode list', async () => {
    mockedModes.mockResolvedValue(MODES_RESPONSE)

    const { result } = renderHook(() => useDiscoveryModes())

    await waitFor(() => expect(result.current.data).toEqual(MODES_RESPONSE))
    expect(mockedModes).toHaveBeenCalledTimes(1)
  })

  it('loads results for an enabled discovery mode', async () => {
    mockedDiscovery.mockResolvedValue(DISCOVERY_RESPONSE)

    const { result } = renderHook(() =>
      useDiscovery({ mode: 'consistently_loved', limit: 20, offset: 0 }, true),
    )

    await waitFor(() =>
      expect(mockedDiscovery).toHaveBeenCalledWith({
        mode: 'consistently_loved',
        limit: 20,
        offset: 0,
      }),
    )
    await waitFor(() => expect(result.current.data).toEqual(DISCOVERY_RESPONSE))
  })

  it('keeps the query disabled until a mode is selected', () => {
    const { result } = renderHook(() =>
      useDiscovery({ mode: 'polarizing', limit: 20, offset: 0 }, false),
    )

    expect(mockedDiscovery).not.toHaveBeenCalled()
    expect(result.current.data).toBeUndefined()
  })
})
