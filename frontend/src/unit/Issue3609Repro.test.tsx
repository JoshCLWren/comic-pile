/* eslint-disable */
// Scratch reproduction for #3609 — removed before commit.
import { type PropsWithChildren } from 'react'
import { render, screen, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { continuityPlansApi } from '../services/api-continuity-plans'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api-threads'
import { tagsApi } from '../services/api-tags'
import { customCBLApi } from '../services/api-custom-cbl'
import ContinuityPlannerPageImpl from '../pages/ContinuityPlannerPage'

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

const _orig = {
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

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})

function wrapper({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const thread = {
  id: 4,
  title: 'Mister Miracle',
  format: 'single issues',
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

beforeEach(() => {
  queryClient.clear()
  continuityPlansApi.get = mocks.get as never
  continuityPlansApi.list = mocks.list as never
  continuityPlansApi.update = mocks.update as never
  dependencyGroupsApi.list = mocks.listGroups as never
  issuesApi.list = mocks.listIssues as never
  threadsApi.list = mocks.listThreads as never
  customCBLApi.list = mocks.cblList as never
  customCBLApi.get = mocks.cblGet as never
  customCBLApi.apply = mocks.cblApply as never
  vi.clearAllMocks()
  mocks.list.mockResolvedValue({ plans: [], next_page_token: null })
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
  queryClient.clear()
  continuityPlansApi.get = _orig.get
  continuityPlansApi.list = _orig.list
  continuityPlansApi.update = _orig.update
  dependencyGroupsApi.list = _orig.groups
  issuesApi.list = _orig.issues
  threadsApi.list = _orig.threads
  customCBLApi.list = _orig.cblList
  customCBLApi.get = _orig.cblGet
  customCBLApi.apply = _orig.cblApply
})

describe('#3609 repro', () => {
  it('refreshes the plan editor after applying a custom CBL server-side', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12/edit']}>
        <Routes>
          <Route path="/continuity-plans/:id/edit" element={<ContinuityPlannerPageImpl />} />
        </Routes>
      </MemoryRouter>,
      { wrapper },
    )

    // Editor hydrated with the saved plan.
    expect(await screen.findByText('Mister Miracle #Annual 1')).toBeVisible()
    expect(screen.getByText(/1 lane · 2 steps/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Save plan' })).toBeDisabled()
    expect(screen.getByRole('status', { name: '' })).toBeTruthy()

    // Open Custom CBLs and choose the saved list.
    await user.click(screen.getByRole('button', { name: 'Create or edit custom CBL' }))
    await user.selectOptions(await screen.findByLabelText('Custom CBL'), '9')

    // Apply it to this Reading Plan.
    const applyButton = await screen.findByRole('button', { name: 'Apply to this Reading Plan' })
    await waitFor(() => expect(applyButton).not.toBeDisabled())
    await user.click(applyButton)

    await waitFor(() => expect(mocks.cblApply).toHaveBeenCalledWith(9, 12))
    expect(await screen.findByText('Applied to Reading Plan: 3 added.')).toBeVisible()

    // The editor must reflect the server-side mutation immediately.
    expect(await screen.findByText(/1 lane · 5 steps/)).toBeVisible()
    expect(screen.getByText('Starman #55')).toBeVisible()
    expect(screen.getByText('All-Star Comics #1')).toBeVisible()
    expect(screen.getByText('JSA #1')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Save plan' })).toBeDisabled()
  })
})
