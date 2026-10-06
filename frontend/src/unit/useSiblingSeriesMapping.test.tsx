import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useCommitSeriesMapping,
  useSiblingSeriesMappingPreview,
} from '../hooks/useSiblingSeriesMapping'
import { seriesMappingApi } from '../services/api-series-mapping'

vi.mock('../services/api-series-mapping', () => ({
  seriesMappingApi: {
    preview: vi.fn(),
    commit: vi.fn(),
  },
}))

const mockedSeriesMappingApi = vi.mocked(seriesMappingApi)

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedSeriesMappingApi.preview.mockReset()
  mockedSeriesMappingApi.commit.mockReset()
})

describe('useSiblingSeriesMappingPreview', () => {
  it('returns a disabled query when required parameters are missing', () => {
    const { result } = renderHook(() => useSiblingSeriesMappingPreview(null, null, null, false), { wrapper })

    expect(result.current.data).toBeUndefined()
    expect(mockedSeriesMappingApi.preview).not.toHaveBeenCalled()
  })

  it('requests a preview with the provided parameters', async () => {
    mockedSeriesMappingApi.preview.mockResolvedValue({
      preview_token: 'tok',
      scope: { status: 'available', scope_key: 'k', origin_issue_id: 1, series_label: 'Saga', basis: 'b' },
      provider_series: null,
      counts: { already_confirmed: 0, safe_exact_match: 0, needs_review_ambiguous: 0, needs_review_conflict: 0, unresolved: 0, excluded_special: 0 },
      rows: [],
      issued_at: 1,
      expires_at: null,
    })

    const { result } = renderHook(() => useSiblingSeriesMappingPreview(1, 'comicvine', '20764'), { wrapper })

    await act(async () => {
      await result.current.refetch()
    })

    expect(mockedSeriesMappingApi.preview).toHaveBeenCalledWith({
      origin_issue_id: 1,
      provider: 'comicvine',
      provider_series_external_id: '20764',
    })
  })
})

describe('useCommitSeriesMapping', () => {
  it('commits the approved rows', async () => {
    mockedSeriesMappingApi.commit.mockResolvedValue({
      idempotency_key: 'k',
      confirmed_issue_ids: [2],
      already_confirmed_issue_ids: [],
      needs_review_issue_ids: [],
      hydration_queued_issue_ids: [],
      series_mapping: { provider: 'comicvine', external_id: '20764', status: 'confirmed', evidence_source: 'user_confirmed' },
    })

    const { result } = renderHook(() => useCommitSeriesMapping(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({
        preview_token: 'tok',
        idempotency_key: 'k',
        approved_row_ids: ['issue:2'],
      })
    })

    expect(mockedSeriesMappingApi.commit).toHaveBeenCalledWith({
      preview_token: 'tok',
      idempotency_key: 'k',
      approved_row_ids: ['issue:2'],
    })
  })
})
