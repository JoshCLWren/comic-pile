import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NewReleasesSection } from '../components/NewReleasesSection'
import { cast } from '../utils/cast'

const mocks = vi.hoisted(() => ({
  updateReleaseSourceEnabled: vi.fn(),
  createReleaseSource: vi.fn(),
  // SAFETY: the hoisted mock starts with no mutation error; the assertion widens the never-assigned null so tests can inject an Error before render.
  enableError: null as Error | null,
  // SAFETY: the hoisted mock starts with no mutation error; the assertion widens the never-assigned null so tests can inject an Error before render.
  followError: null as Error | null,
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
      createReleaseSource: mocks.createReleaseSource,
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
      error: mocks.enableError,
      mutate: mocks.updateReleaseSourceEnabled,
    }),
    useCreateReleaseSource: () => ({
      isPending: false,
      error: mocks.followError,
      mutate: mocks.createReleaseSource,
    }),
  }
})

const mockUpdate = cast<ReturnType<typeof vi.fn>>(mocks.updateReleaseSourceEnabled)
const mockCreate = cast<ReturnType<typeof vi.fn>>(mocks.createReleaseSource)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/continuity-plans/12']}>{children}</MemoryRouter>
      </QueryClientProvider>
    )
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
  thread_id: 5,
  provider_title: 'Incredible Hulk',
  enabled: false,
  last_synced_at: null,
}

const sourceWithoutTitle = {
  ...enabledSource,
  source_id: 903,
  thread_id: 6,
  provider_title: '',
  provider_publisher: null,
  provider_start_year: null,
  provider_issue_count: null,
  enabled: false,
  last_synced_at: null,
}

const sourceWithInvalidSync = {
  ...enabledSource,
  source_id: 904,
  thread_id: 7,
  provider_title: 'Invalid Sync',
  last_synced_at: 'not-a-date',
}

const confirmedCandidate = {
  thread_id: 12,
  thread_title: 'Ultimate Spider-Man',
  mapping_state: 'confirmed' as const,
  external_identity_id: 501,
  provider_volume_id: '60520-1234',
  provider_title: 'Ultimate Spider-Man (2024)',
  provider_publisher: 'Marvel',
  provider_start_year: 2024,
  provider_issue_count: 8,
  mapping_status: 'confirmed',
  enableable: true,
  followed: false,
}

const ambiguousCandidate = {
  thread_id: 13,
  thread_title: 'Ultimate X-Men',
  mapping_state: 'ambiguous' as const,
  external_identity_id: 502,
  provider_volume_id: '60521-5678',
  provider_title: 'Ultimate X-Men (2024)',
  provider_publisher: 'Marvel',
  provider_start_year: 2024,
  provider_issue_count: 6,
  mapping_status: 'candidate',
  enableable: false,
  followed: false,
}

const unmappedCandidate = {
  thread_id: 14,
  thread_title: 'Unmapped Series',
  mapping_state: 'unmapped' as const,
  external_identity_id: null,
  provider_volume_id: null,
  provider_title: null,
  provider_publisher: null,
  provider_start_year: null,
  provider_issue_count: null,
  mapping_status: null,
  enableable: false,
  followed: false,
}

// Candidate without provider_title but with provider_volume_id (for missing-title tests)
const candidateWithoutTitle = {
  ...confirmedCandidate,
  thread_id: 20,
  thread_title: 'Same Thread',
  external_identity_id: 601,
  provider_volume_id: '7000-100',
  provider_title: '',
  provider_publisher: null,
  provider_start_year: null,
  provider_issue_count: null,
}

// Second candidate on same thread, different volume ID (for distinct volumes test)
const candidateWithoutTitleSecond = {
  ...confirmedCandidate,
  thread_id: 20,
  thread_title: 'Same Thread',
  external_identity_id: 602,
  provider_volume_id: '7000-101',
  provider_title: '',
  provider_publisher: null,
  provider_start_year: null,
  provider_issue_count: null,
}

// Candidate with zero issue count
const candidateZeroIssues = {
  ...confirmedCandidate,
  thread_id: 21,
  thread_title: 'Zero Issues Thread',
  external_identity_id: 603,
  provider_volume_id: '8000-200',
  provider_title: 'Zero Issues Title',
  provider_publisher: 'Test Publisher',
  provider_start_year: 2024,
  provider_issue_count: 0,
}

// Candidate with one issue
const candidateOneIssue = {
  ...confirmedCandidate,
  thread_id: 22,
  thread_title: 'One Issue Thread',
  external_identity_id: 604,
  provider_volume_id: '8000-201',
  provider_title: 'One Issue Title',
  provider_publisher: 'Test Publisher',
  provider_start_year: 2024,
  provider_issue_count: 1,
}

// Candidate with multiple issues
const candidateManyIssues = {
  ...confirmedCandidate,
  thread_id: 23,
  thread_title: 'Many Issues Thread',
  external_identity_id: 605,
  provider_volume_id: '8000-202',
  provider_title: 'Many Issues Title',
  provider_publisher: 'Test Publisher',
  provider_start_year: 2024,
  provider_issue_count: 5,
}

describe('NewReleasesSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.enableError = null
    mocks.followError = null
    mockUpdate.mockResolvedValue({ ...enabledSource, enabled: false })
    mockCreate.mockResolvedValue({ id: 1, plan_id: 12 })
  })

  it('renders followed volumes with target threads and sync status', () => {
    render(
      <NewReleasesSection planId={12} sources={[enabledSource, disabledSource]} candidates={[]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByRole('heading', { name: 'New releases' })).toBeInTheDocument()
    expect(screen.getByText(/X-Men/)).toBeInTheDocument()
    expect(screen.getByText('Target thread #4')).toBeInTheDocument()
    expect(screen.getByText('Target thread #5')).toBeInTheDocument()
    expect(screen.getAllByText(/Last sync:/)).toHaveLength(2)
    expect(screen.getByText('Last sync: Never synced')).toBeInTheDocument()
    expect(screen.getByText(/Incredible Hulk/)).toBeInTheDocument()
    expect(screen.getAllByTestId('new-release-source')).toHaveLength(2)
  })

  it('shows an empty state with a working Queue mapping repair link', () => {
    render(<NewReleasesSection planId={12} sources={[]} candidates={[]} />, {
      wrapper: createWrapper(),
    })
    expect(screen.getByRole('heading', { name: 'New releases' })).toBeInTheDocument()
    expect(screen.queryByTestId('new-release-source')).not.toBeInTheDocument()
    expect(screen.queryByTestId('new-release-candidate')).not.toBeInTheDocument()
    const repairLink = screen.getByRole('link', { name: 'Queue mapping repair' })
    expect(repairLink).toHaveAttribute('href', '/queue')
  })

  it('shows the v1 limit copy in the empty state and with candidates', () => {
    const { unmount } = render(
      <NewReleasesSection planId={12} sources={[]} candidates={[]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText(/does not import future solicitations/)).toBeInTheDocument()
    unmount()

    render(
      <NewReleasesSection
        planId={12}
        sources={[]}
        candidates={[confirmedCandidate, unmappedCandidate]}
      />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText(/does not import future solicitations/)).toBeInTheDocument()
  })

  it('toggles an enabled source off and reports the new state', async () => {
    render(<NewReleasesSection planId={12} sources={[enabledSource]} candidates={[]} />, {
      wrapper: createWrapper(),
    })
    const toggle = screen.getByRole('button', { name: 'Stop following X-Men · Marvel · 1963 · 12 issues' })
    toggle.click()
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ sourceId: 901, enabled: false }),
    )
    expect(mockUpdate).toHaveBeenCalledTimes(1)
  })

  it('toggles a disabled source on', async () => {
    render(<NewReleasesSection planId={12} sources={[disabledSource]} candidates={[]} />, {
      wrapper: createWrapper(),
    })
    const toggle = screen.getByRole('button', { name: 'Follow Incredible Hulk · Marvel · 1963 · 12 issues' })
    toggle.click()
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ sourceId: 902, enabled: true }),
    )
  })

  it('lists confirmed candidates with their provider metadata and thread', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[confirmedCandidate]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByTestId('new-release-candidate')).toBeInTheDocument()
    expect(
      screen.getByText('Ultimate Spider-Man (2024) · Marvel · 2024 · 8 issues'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Target thread #12 · Ultimate Spider-Man'),
    ).toBeInTheDocument()
  })

  it('creates a release source when a candidate is followed', async () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[confirmedCandidate]} />,
      { wrapper: createWrapper() },
    )
    const follow = screen.getByRole('button', {
      name: 'Follow Ultimate Spider-Man (2024)',
    })
    follow.click()
    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        plan_id: 12,
        thread_id: 12,
        external_identity_id: 501,
      }),
    )
    expect(mockCreate).toHaveBeenCalledTimes(1)
  })

  it('does not offer an ambiguous mapping as followable but links to repair', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[ambiguousCandidate]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByTestId('new-release-blocked-candidate')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Follow Ultimate X-Men (2024)' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/not confirmed yet/)).toBeInTheDocument()
    const repairLink = screen.getByRole('link', { name: 'Repair the mapping' })
    expect(repairLink).toHaveAttribute('href', '/queue')
  })

  it('does not offer an unmapped thread as followable but explains the required step', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[unmappedCandidate]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByTestId('new-release-blocked-candidate')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /^Follow/ }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/No ComicVine volume is mapped to this thread/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Repair the mapping' })).not.toBeInTheDocument()
    expect(screen.getByText(/Track issues in this thread first/)).toBeInTheDocument()
  })

  it('offers an ambiguous mapping a Repair the mapping link', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[ambiguousCandidate]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByTestId('new-release-blocked-candidate')).toBeInTheDocument()
    expect(screen.getByText(/not confirmed yet/)).toBeInTheDocument()
    const repairLink = screen.getByRole('link', { name: 'Repair the mapping' })
    expect(repairLink).toHaveAttribute('href', '/queue')
  })

  it('shows a visible error when following a candidate fails', () => {
    mocks.followError = new Error('Could not follow this volume.')
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[confirmedCandidate]} />,
      { wrapper: createWrapper() },
    )
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Could not follow this volume.')
  })

  it('shows a visible error when toggling a followed source fails', () => {
    mocks.enableError = new Error('Could not update this volume.')
    render(<NewReleasesSection planId={12} sources={[enabledSource]} candidates={[]} />, {
      wrapper: createWrapper(),
    })
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Could not update this volume.')
  })

  it('falls back to readable label when provider_title is empty', () => {
    render(
      <NewReleasesSection planId={12} sources={[sourceWithoutTitle]} candidates={[]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('ComicVine volume 4000-77')).toBeInTheDocument()
    expect(screen.queryByText(/X-Men/)).not.toBeInTheDocument()
  })

  it('shows Never synced for invalid last_synced_at', () => {
    render(
      <NewReleasesSection planId={12} sources={[sourceWithInvalidSync]} candidates={[]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('Last sync: Never synced')).toBeInTheDocument()
  })

  it('renders volume label without metadata when only title is present', () => {
    const minimalSource = {
      ...enabledSource,
      source_id: 905,
      provider_title: 'Minimal Title',
      provider_publisher: null,
      provider_start_year: null,
      provider_issue_count: null,
    }
    render(
      <NewReleasesSection planId={12} sources={[minimalSource]} candidates={[]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('Minimal Title')).toBeInTheDocument()
    expect(screen.queryByText(/·/)).not.toBeInTheDocument()
  })

  it('shows readable fallback with volume ID for candidate missing provider_title', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[candidateWithoutTitle]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('Same Thread · ComicVine volume 7000-100')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Follow Same Thread · ComicVine volume 7000-100' })).toBeInTheDocument()
  })

  it('distinguishes multiple candidates on same thread when both lack provider_title', () => {
    render(
      <NewReleasesSection
        planId={12}
        sources={[]}
        candidates={[candidateWithoutTitle, candidateWithoutTitleSecond]}
      />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('Same Thread · ComicVine volume 7000-100')).toBeInTheDocument()
    expect(screen.getByText('Same Thread · ComicVine volume 7000-101')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Follow Same Thread · ComicVine volume 7000-100' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Follow Same Thread · ComicVine volume 7000-101' })).toBeInTheDocument()
  })

  it('renders zero issues correctly in candidate label', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[candidateZeroIssues]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('Zero Issues Title · Test Publisher · 2024 · 0 issues')).toBeInTheDocument()
  })

  it('renders one issue correctly in candidate label (singular)', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[candidateOneIssue]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('One Issue Title · Test Publisher · 2024 · 1 issue')).toBeInTheDocument()
  })

  it('renders multiple issues correctly in candidate label (plural)', () => {
    render(
      <NewReleasesSection planId={12} sources={[]} candidates={[candidateManyIssues]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('Many Issues Title · Test Publisher · 2024 · 5 issues')).toBeInTheDocument()
  })

  it('renders zero issues correctly in followed source label', () => {
    const zeroIssueSource = {
      ...enabledSource,
      source_id: 906,
      provider_title: 'Zero Issue Source',
      provider_publisher: 'Test Publisher',
      provider_start_year: 2024,
      provider_issue_count: 0,
    }
    render(
      <NewReleasesSection planId={12} sources={[zeroIssueSource]} candidates={[]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('Zero Issue Source · Test Publisher · 2024 · 0 issues')).toBeInTheDocument()
  })

  it('renders one issue correctly in followed source label (singular)', () => {
    const oneIssueSource = {
      ...enabledSource,
      source_id: 907,
      provider_title: 'One Issue Source',
      provider_publisher: 'Test Publisher',
      provider_start_year: 2024,
      provider_issue_count: 1,
    }
    render(
      <NewReleasesSection planId={12} sources={[oneIssueSource]} candidates={[]} />,
      { wrapper: createWrapper() },
    )
    expect(screen.getByText('One Issue Source · Test Publisher · 2024 · 1 issue')).toBeInTheDocument()
  })
})
