import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreatorTeamChemistry } from '../hooks/useCreatorTeamChemistry'
import { creatorTeamChemistryApi } from '../services/creatorTeamChemistryApi'
import type { CreatorTeamChemistryResponse } from '../types/index'

vi.mock('../services/creatorTeamChemistryApi', () => ({
  creatorTeamChemistryApi: {
    getChemistry: vi.fn(),
  },
}))

const mockedGetChemistry = vi.mocked(creatorTeamChemistryApi.getChemistry)

function makeResponse(): CreatorTeamChemistryResponse {
  return {
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
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedGetChemistry.mockResolvedValue(makeResponse())
})

describe('useCreatorTeamChemistry', () => {
  it('fetches through the canonical query key once enabled', async () => {
    const { result } = renderHook(() => useCreatorTeamChemistry(), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(mockedGetChemistry).toHaveBeenCalledTimes(1)
    expect(result.current.data?.min_shared_team_sample).toBe(3)
    expect(result.current.isError).toBe(false)
  })

  it('stays disabled when the caller disables it', async () => {
    const { result } = renderHook(() => useCreatorTeamChemistry(false), {
      wrapper: createWrapper(),
    })

    expect(result.current.isPending).toBe(true)
    expect(mockedGetChemistry).not.toHaveBeenCalled()
  })
})
