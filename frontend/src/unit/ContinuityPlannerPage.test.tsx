import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ContinuityPlannerPage from '../pages/ContinuityPlannerPage'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
  listGroups: vi.fn(),
  listIssues: vi.fn(),
  getIssue: vi.fn(),
  listThreads: vi.fn(),
  getThread: vi.fn(),
}))

vi.mock('../services/api-continuity-plans', () => ({
  continuityPlansApi: {
    create: mocks.create,
    get: mocks.get,
    update: mocks.update,
  },
}))

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: { list: mocks.listGroups },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: { list: mocks.listIssues, get: mocks.getIssue },
}))

vi.mock('../services/api', () => ({
  threadsApi: { list: mocks.listThreads, get: mocks.getThread },
}))

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

const issue = {
  id: 40,
  thread_id: 4,
  issue_number: 'Annual 1',
  position: 1,
  status: 'unread',
  read_at: null,
  created_at: '2026-08-12T00:00:00Z',
}

beforeEach(() => {
  window.localStorage.clear()
  mocks.listThreads.mockResolvedValue({ threads: [thread], next_page_token: null })
  mocks.listGroups.mockResolvedValue([{ id: 8, name: 'Fourth World', memberships: [], created_at: '2026-08-12T00:00:00Z' }])
  mocks.listIssues.mockResolvedValue({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
  mocks.create.mockResolvedValue({
    id: 12,
    user_id: 1,
    name: 'Kirby lane',
    ordering_mode: 'strict_sequential',
    lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
    nodes: [],
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  })
})

describe('ContinuityPlannerPage', () => {
  it('creates a sequential plan from shared human-facing selectors', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.clear(await screen.findByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Kirby lane')
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Kirby lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        expect.objectContaining({ node_type: 'issue', ref_id: 40, position: 0 }),
        expect.objectContaining({ node_type: 'crossover', ref_id: 8, position: 1 }),
      ],
    }))
  })

  it('restores saved order when unsaved changes are canceled', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [{ id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 0 }],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Fourth World')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Remove Fourth World' }))
    expect(screen.getByText('Unsaved changes')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(screen.getByText('Fourth World')).toBeVisible()
    expect(mocks.update).not.toHaveBeenCalled()
  })
})
