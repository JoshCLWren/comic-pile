import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingPlanDetailPage from '../pages/ReadingPlanDetailPage'
import { continuityPlansApi, type ReadingPlanReaderView } from '../services/api-continuity-plans'
import { tagsApi } from '../services/api-tags'
import { cast } from '../utils/cast'

vi.mock('../services/api-continuity-plans', async () => {
  const actual = await vi.importActual<typeof import('../services/api-continuity-plans')>(
    '../services/api-continuity-plans',
  )
  return {
    ...actual,
    continuityPlansApi: {
      ...actual.continuityPlansApi,
      getReader: vi.fn(),
    },
  }
})

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    threadIssuesEffective: vi.fn().mockResolvedValue({ thread_id: 1, issues: [] }),
    effectiveForPlan: vi.fn(),
    unassign: vi.fn(),
  },
}))

vi.mock('../components/ReadingPlanAddMaterial', () => ({
  default: () => <div data-testid="add-from-cbl">Add from CBL</div>,
}))

vi.mock('../components/Tags/TagSection', () => ({
  TagSection: () => <div data-testid="reading-plan-tags">Tags</div>,
}))

const mockGetReader = cast<ReturnType<typeof vi.fn>>(continuityPlansApi.getReader)
const mockPlanTags = vi.mocked(tagsApi.effectiveForPlan)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function renderPage(planId = '12') {
  return render(
    <MemoryRouter initialEntries={[`/continuity-plans/${planId}`]}>
      <Routes>
        <Route path="/continuity-plans/:id" element={<ReadingPlanDetailPage />} />
        <Route path="/continuity-plans/:id/edit" element={<div>Editor</div>} />
        <Route path="/thread/:id" element={<div>Thread page</div>} />
      </Routes>
    </MemoryRouter>,
    { wrapper: createWrapper() },
  )
}

const blockedIssue = {
  occurrence_id: 'c75',
  issue_id: 75,
  lane_id: 'main',
  display_position: 1,
  issue_number: '75',
  thread_id: 8,
  thread_title: 'Cable',
  status: 'unread',
  availability: 'blocked' as const,
  blockers: [
    {
      issue_id: 95,
      thread_id: 4,
      thread_title: 'X-Men',
      issue_number: '95',
      explanation: 'Blocked by X-Men: #95',
    },
  ],
  source_paths: ['Marvel/Age of Apocalypse.cbl'],
}

const availableIssue = {
  occurrence_id: 'x95',
  issue_id: 95,
  lane_id: 'main',
  display_position: 0,
  issue_number: '95',
  thread_id: 4,
  thread_title: 'X-Men',
  status: 'unread',
  availability: 'available' as const,
  blockers: [],
  source_paths: ['Marvel/Age of Apocalypse.cbl'],
}

const laterIssue = {
  occurrence_id: 'c76',
  issue_id: 76,
  lane_id: 'main',
  display_position: 2,
  issue_number: '76',
  thread_id: 8,
  thread_title: 'Cable',
  status: 'unread',
  availability: 'later' as const,
  blockers: [],
  source_paths: ['Marvel/Age of Apocalypse.cbl'],
}

const readerView: ReadingPlanReaderView = {
  plan_id: 12,
  name: 'Age of Apocalypse',
  ordering_mode: 'informational',
  progress: { total_issues: 3, read_issues: 0 },
  available_now: [availableIssue],
  blocked_next: [blockedIssue],
  lanes: [
    {
      id: 'main',
      name: 'Main',
      order: 0,
      issues: [availableIssue, blockedIssue, laterIssue],
    },
  ],
  sources: [
    {
      id: 1,
      raw_source_path: 'Marvel/Age of Apocalypse.cbl',
      repository: null,
      source_path: null,
      revision_sha: null,
      content_hash: null,
      adopted_at: null,
      recorded_at: '2026-10-12T00:00:00Z',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetReader.mockResolvedValue(readerView)
  mockPlanTags.mockResolvedValue({
    target_type: 'ContinuityPlan',
    target_id: 12,
    direct_tags: [],
    effective_tags: [],
  })
})

describe('ReadingPlanDetailPage', () => {
  it('shows progress, available now, and the actual blocker', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Age of Apocalypse' })).toBeInTheDocument()
    expect(screen.getByTestId('plan-progress')).toHaveTextContent('0%')
    expect(screen.getByText('Informational')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Available now' })).toBeInTheDocument()
    expect(screen.getAllByText('X-Men #95').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'Blocked next' })).toBeInTheDocument()
    expect(within(screen.getByTestId('blocked-next')).getByText('Blocked by X-Men: #95')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Upcoming' })).toBeInTheDocument()
    expect(within(screen.getByTestId('upcoming-material')).getByText('Cable #76')).toBeInTheDocument()
    expect(screen.getByText('Source reading order')).toBeInTheDocument()
    expect(screen.getByText('CBL-backed')).toBeInTheDocument()
    expect(screen.getByText('Marvel/Age of Apocalypse.cbl')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continue reading' })).toHaveAttribute('href', '/thread/4')
    expect(screen.getByRole('button', { name: 'Edit plan' })).toBeInTheDocument()
    expect(screen.queryByText(/ContinuityRule/i)).not.toBeInTheDocument()
  })

  it('rejects an invalid plan id before fetching', () => {
    renderPage('not-a-number')
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid reading plan ID.')
    expect(mockGetReader).not.toHaveBeenCalled()
  })
})
