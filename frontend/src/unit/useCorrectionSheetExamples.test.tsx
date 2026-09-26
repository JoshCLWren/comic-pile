import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import { useCorrectionSheetExamples } from '../hooks/useCorrectionSheetExamples'
import { sessionApi } from '../services/api-sessions'
import { queryKeys } from '../query/queryKeys'

vi.mock('../services/api-sessions', () => ({
  sessionApi: {
    getCorrectionExamples: vi.fn(),
  },
}))

const mockedSessionApi = vi.mocked(sessionApi)

function renderExamples(enabled: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderHook(() => useCorrectionSheetExamples(enabled), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

describe('useCorrectionSheetExamples', () => {
  beforeEach(() => {
    mockedSessionApi.getCorrectionExamples.mockReset()
  })

  it('issues no request while the sheet is closed', () => {
    const { result } = renderExamples(false)

    expect(result.current.examples).toBeUndefined()
    expect(mockedSessionApi.getCorrectionExamples).not.toHaveBeenCalled()
  })

  it('serves the whole sheet with one bounded request keyed under the session namespace', async () => {
    mockedSessionApi.getCorrectionExamples.mockResolvedValue({
      even_easier: 'Think more like Pal Jimmy Olsen #134.',
      keep_level_different: null,
      something_familiar: 'Based on your ratings, think more Planetary territory.',
      something_different: null,
      pure_random: null,
    })

    const { result } = renderExamples(true)

    await waitFor(() => {
      expect(result.current.examples?.even_easier).toBe('Think more like Pal Jimmy Olsen #134.')
    })
    expect(result.current.examples?.something_familiar).toBe(
      'Based on your ratings, think more Planetary territory.',
    )
    // The whole sheet is one request, not one per option.
    expect(mockedSessionApi.getCorrectionExamples).toHaveBeenCalledTimes(1)
  })

  it('normalizes a missing field to null instead of inheriting another choice example', async () => {
    mockedSessionApi.getCorrectionExamples.mockResolvedValue({
      even_easier: 'Think more like Pal Jimmy Olsen #134.',
    } as Awaited<ReturnType<typeof sessionApi.getCorrectionExamples>>)

    const { result } = renderExamples(true)

    await waitFor(() => {
      expect(result.current.examples?.even_easier).toBe('Think more like Pal Jimmy Olsen #134.')
    })
    expect(result.current.examples).toEqual({
      even_easier: 'Think more like Pal Jimmy Olsen #134.',
      keep_level_different: null,
      something_familiar: null,
      something_different: null,
      pure_random: null,
    })
  })

  it('leaves the sheet on plain copy when the lookup fails', async () => {
    mockedSessionApi.getCorrectionExamples.mockRejectedValue(new Error('network down'))

    const { result } = renderExamples(true)

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
    expect(result.current.examples).toBeUndefined()
  })

  it('builds its query key through queryKeys.session', () => {
    expect(queryKeys.session.correctionExamples()).toEqual(['session', 'correction-examples'])
  })
})
