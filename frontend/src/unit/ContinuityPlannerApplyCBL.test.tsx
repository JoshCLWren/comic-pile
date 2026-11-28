import { type PropsWithChildren } from 'react'
import { render, screen, within, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { continuityPlansApi, type ContinuityPlanListItem } from '../services/api-continuity-plans'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api-threads'
import { customCBLApi } from '../services/api-custom-cbl'
import ContinuityPlannerPage from '../pages/ContinuityPlannerPage'
import { queryKeys } from '../query/queryKeys'

const mocks = {
  get: vi.fn(),
  list: vi.fn(),
  update: vi.fn(),
  listGroups: vi.fn(),
  listIssues: vi.fn(),
  listThreads: vi.fn(),
  cblList: vi.fn(),
  cblGet: vi.fn(),
  cblApply: vi.fn(),
}

const original = {
  get: continuityPlansApi.get,
  list: continuityPlansApi.list,
  update: continuityPlansApi.update,
  groups: dependencyGroupsApi.list,
  issues: issuesApi.list,
  threads: threadsApi.list,
  cblList: customCBLApi.list,
  cblGet: customCBLApi.get,
  cblApply: customCBLApi.apply,
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function ReadingPlanListRefreshBarrier({
  queryFn,
}: {
  queryFn: () => Promise<ContinuityPlanListItem[]>
}) {
  useQuery({
    queryKey: queryKeys.readingPlans.list(),
    queryFn,
    initialData: [],
    staleTime: Infinity,
  })
  return null
}

const thread = {
  id: 4,
  title: 'Mister Miracle',
  issues_remaining: 12,
  total_issues: 12,
  queue_position: 1,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-08-12T00:00:00Z',
}

const basePlan = {
  id: 12,
  user_id: 1,
  name: 'Saved lane',
  ordering_mode: 'informational',
  lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
  nodes: [
    { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0, label: 'Mister Miracle #Annual 1' },
    { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1, label: 'Fourth World' },
  ],
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

const committedPlan = {
  ...basePlan,
  nodes: [
    ...basePlan.nodes,
    { id: 'issue-26360', node_type: 'issue', ref_id: 26360, lane_id: 'main', position: 2, label: 'Starman #55' },
    { id: 'issue-30001', node_type: 'issue', ref_id: 30001, lane_id: 'main', position: 3, label: 'All-Star Comics #1' },
    { id: 'issue-30002', node_type: 'issue', ref_id: 30002, lane_id: 'main', position: 4, label: 'JSA #1' },
  ],
  updated_at: '2026-10-13T07:00:00Z',
  added_issue_ids: [26360, 30001, 30002],
  skipped_existing_issue_ids: [],
}

const customList = {
  id: 9,
  user_id: 1,
  name: 'Starman into JSA',
  description: null,
  mode: 'loose',
  issue_count: 3,
  created_at: '2026-09-14T03:00:00Z',
  updated_at: '2026-09-14T03:00:00Z',
  entries: [
    { id: 91, position: 0, issue_id: 26360, thread_id: 180, series_name: 'Starman', issue_number: '55', status: 'unread', is_checkpoint: false, gate: 'none', skipped: false },
    { id: 92, position: 1, issue_id: 30001, thread_id: 9001, series_name: 'All-Star Comics', issue_number: '1', status: 'unread', is_checkpoint: false, gate: 'none', skipped: false },
    { id: 93, position: 2, issue_id: 30002, thread_id: 9002, series_name: 'JSA', issue_number: '1', status: 'unread', is_checkpoint: false, gate: 'none', skipped: false },
  ],
}

describe('ContinuityPlannerPage - Custom CBL apply (#3609)', () => {
  let client: QueryClient

  beforeEach(() => {
    client = makeQueryClient()
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    continuityPlansApi.get = mocks.get as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    continuityPlansApi.list = mocks.list as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    continuityPlansApi.update = mocks.update as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    dependencyGroupsApi.list = mocks.listGroups as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    issuesApi.list = mocks.listIssues as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    threadsApi.list = mocks.listThreads as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    customCBLApi.list = mocks.cblList as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    customCBLApi.get = mocks.cblGet as never
    // SAFETY: each API method is replaced by a vi.fn() stub configured below and restored in afterEach.
    customCBLApi.apply = mocks.cblApply as never
    vi.clearAllMocks()
    mocks.list.mockResolvedValue([])
    mocks.listGroups.mockResolvedValue([{ id: 8, name: 'Fourth World', memberships: [], created_at: '2026-08-12T00:00:00Z' }])
    mocks.listIssues.mockResolvedValue({ issues: [], total_count: 0, page_size: 100, next_page_token: null })
    mocks.listThreads.mockResolvedValue({ threads: [thread], next_page_token: null })
    mocks.get.mockResolvedValue(basePlan)
    mocks.cblList.mockResolvedValue([
      { id: 9, name: customList.name, description: null, mode: 'loose', issue_count: 3, updated_at: customList.updated_at },
    ])
    mocks.cblGet.mockResolvedValue(customList)
    mocks.cblApply.mockResolvedValue(committedPlan)
  })

  afterEach(() => {
    cleanup()
    client.clear()
    continuityPlansApi.get = original.get
    continuityPlansApi.list = original.list
    continuityPlansApi.update = original.update
    dependencyGroupsApi.list = original.groups
    issuesApi.list = original.issues
    threadsApi.list = original.threads
    customCBLApi.list = original.cblList
    customCBLApi.get = original.cblGet
    customCBLApi.apply = original.cblApply
  })

  it('adopts applied steps before dependent refreshes and preserves them on a later save', async () => {
    let signalRefreshStarted!: () => void
    const refreshStarted = new Promise<void>((resolve) => {
      signalRefreshStarted = resolve
    })
    let releaseRefresh!: () => void
    const refreshReleased = new Promise<void>((resolve) => {
      releaseRefresh = resolve
    })
    const holdListRefresh = vi.fn(async () => {
      signalRefreshStarted()
      await refreshReleased
      return []
    })

    render(
      <MemoryRouter initialEntries={['/continuity-plans/12/edit']}>
        <Routes>
          <Route
            path="/continuity-plans/:id/edit"
            element={
              <>
                <ContinuityPlannerPage />
                <ReadingPlanListRefreshBarrier queryFn={holdListRefresh} />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
      { wrapper: wrapper(client) },
    )

    const user = userEvent.setup()

    expect(await screen.findByText('Mister Miracle #Annual 1')).toBeVisible()
    expect(screen.getByText(/1 lane · 2 steps/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Save plan' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')

    const applyButton = await screen.findByRole('button', { name: 'Apply to this Reading Plan' })
    await waitFor(() => expect(applyButton).not.toBeDisabled())
    await user.click(applyButton)

    await waitFor(() => expect(mocks.cblApply).toHaveBeenCalledWith(9, 12))
    await refreshStarted

    // A slow dependent query must not leave the committed plan out of the editor.
    expect(await screen.findByText(/1 lane · 5 steps/)).toBeVisible()
    const laneMain = screen.getByTestId('lane-main')
    expect(within(laneMain).getByText('Starman #55')).toBeVisible()
    expect(within(laneMain).getByText('All-Star Comics #1')).toBeVisible()
    expect(within(laneMain).getByText('JSA #1')).toBeVisible()

    releaseRefresh()
    expect(await screen.findByText('Applied to Reading Plan: 3 added.')).toBeVisible()
    expect(await screen.findByRole('button', { name: 'Save plan' })).toBeDisabled()

    mocks.update.mockResolvedValue({
      ...committedPlan,
      name: 'Saved after CBL',
      updated_at: '2026-10-13T08:00:00Z',
    })
    const planName = screen.getByLabelText('Plan name')
    await user.clear(planName)
    await user.type(planName, 'Saved after CBL')
    const saveButton = screen.getByRole('button', { name: 'Save plan' })
    expect(saveButton).toBeEnabled()
    await user.click(saveButton)

    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1))
    expect(mocks.update).toHaveBeenCalledWith(
      12,
      expect.objectContaining({
        name: 'Saved after CBL',
        expected_updated_at: committedPlan.updated_at,
      }),
    )
    const payload = mocks.update.mock.calls[0][1]
    expect(payload.nodes).toHaveLength(5)
    expect(payload.nodes.map((node: { id: string }) => node.id)).toEqual(
      committedPlan.nodes.map((node) => node.id),
    )
    expect(await screen.findByDisplayValue('Saved after CBL')).toBeVisible()
    expect(screen.getByText(/1 lane · 5 steps/)).toBeVisible()
  })
})
