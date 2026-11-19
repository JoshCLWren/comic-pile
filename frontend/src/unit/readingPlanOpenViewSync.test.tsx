import { act, renderHook, waitFor } from '@testing-library/react'
import { focusManager, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { useReadingPlanReader } from '../hooks/useReadingPlans'
import { useIssueCards } from '../hooks/useIssueCards'
import { createAppQueryClient } from '../query/queryClient'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { issueCardsApi } from '../services/issueCardsApi'

afterEach(() => {
  vi.restoreAllMocks()
  focusManager.setFocused(undefined)
})

function setup() {
  const client = createAppQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return wrapper
}

async function refocus() {
  await act(async () => {
    focusManager.setFocused(false)
    focusManager.setFocused(true)
  })
}

it('refetches the plan reader when the tab regains focus (#5486)', async () => {
  // SAFETY: the reader payload is opaque to this hook-level focus test.
  const getReader = vi.spyOn(continuityPlansApi, 'getReader').mockResolvedValue({} as never)
  const { result } = renderHook(() => useReadingPlanReader(7), { wrapper: setup() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(getReader).toHaveBeenCalledTimes(1)
  await refocus()
  await waitFor(() => expect(getReader).toHaveBeenCalledTimes(2))
})

it('refetches plan issue cards on focus when opted in (#5486)', async () => {
  const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards').mockResolvedValue([])
  const { result } = renderHook(
    () => useIssueCards([1, 2], { refetchOnWindowFocus: 'always' }),
    { wrapper: setup() },
  )
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  await refocus()
  await waitFor(() => expect(fetchCards).toHaveBeenCalledTimes(2))
})

it('keeps default issue-card focus behavior for other callers', async () => {
  const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards').mockResolvedValue([])
  const { result } = renderHook(() => useIssueCards([3]), { wrapper: setup() })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  await refocus()
  expect(fetchCards).toHaveBeenCalledTimes(1)
})
