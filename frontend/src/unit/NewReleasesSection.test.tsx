import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NewReleasesSection } from '../components/NewReleasesSection'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { cast } from '../utils/cast'

const mocks = vi.hoisted(() => ({
  updateReleaseSourceEnabled: vi.fn(),
}))

vi.mock('../services/api-continuity-plans', async () => {
  const actual = await vi.importActual<typeof import('../services/api-continuity-plans')>(
    '../services/api-continuity-plans',
  )
  return {
    ...actual,
    continuityPlansApi: {
      ...actual.continuityPlansApi,
      updateReleaseSourceEnabled: mocks.updateReleaseSourceEnabled,
    },
  }
})

vi.mock('../hooks/useReleaseSources', async () => {
  const actual = await vi.importActual<typeof import('../hooks/useReleaseSources')>(
    '../hooks/useReleaseSources',
  )
  return {
    ...actual,
    useEnableReleaseSource: () => ({
      isPending: false,
      mutate: mocks.updateReleaseSourceEnabled,
    }),
  }
})

const mockUpdate = cast<ReturnType<typeof vi.fn>>(mocks.updateReleaseSourceEnabled)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const enabledSource = {
  source_id: 901,
  thread_id: 4,
  external_identity_id: 77,
  provider_volume_id: '4000-77',
  provider_title: 'X-Men',
  provider_publisher: 'Marvel',
  provider_start_year: 1963,
  provider_issue_count: 12,
  enabled: true,
  last_synced_at: '2026-10-17T05:00:00Z',
}

const disabledSource = {
  ...enabledSource,
  source_id: 902,
  provider_title: 'Incredible Hulk',
  enabled: false,
  last_synced_at: null,
}

describe('NewReleasesSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUpdate.mockResolvedValue({ ...enabledSource, enabled: false })
  })

  it('renders followed volumes with target threads and sync status', () => {
    render(
      <NewReleasesSection
        sources={[enabledSource, disabledSource]}
        emptyLabel="No sources"
      />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByRole('heading', { name: 'New releases' })).toBeInTheDocument()
    expect(screen.getByText('X-Men')).toBeInTheDocument()
    expect(screen.getByText('Target thread #4')).toBeInTheDocument()
    expect(screen.getByText(/Last sync:/)).toBeInTheDocument()
    expect(screen.getByText('Incredible Hulk')).toBeInTheDocument()
    expect(screen.getAllByTestId('new-release-source')).toHaveLength(2)
  })

  it('shows an empty state when no sources are subscribed', () => {
    render(<NewReleasesSection sources={[]} emptyLabel="No sources" />, {
      wrapper: createWrapper(),
    })
    expect(screen.getByRole('heading', { name: 'New releases' })).toBeInTheDocument()
    expect(screen.getByText('No sources')).toBeInTheDocument()
    expect(screen.queryByTestId('new-release-source')).not.toBeInTheDocument()
  })

  it('toggles an enabled source off and reports the new state', async () => {
    render(<NewReleasesSection sources={[enabledSource]} emptyLabel="No sources" />, {
      wrapper: createWrapper(),
    })
    const toggle = screen.getByRole('button', { name: 'Enabled' })
    toggle.click()
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith(901, false))
    expect(mockUpdate).toHaveBeenCalledTimes(1)
  })

  it('toggles a disabled source on', async () => {
    render(<NewReleasesSection sources={[disabledSource]} emptyLabel="No sources" />, {
      wrapper: createWrapper(),
    })
    const toggle = screen.getByRole('button', { name: 'Enable' })
    toggle.click()
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith(902, true))
  })
})