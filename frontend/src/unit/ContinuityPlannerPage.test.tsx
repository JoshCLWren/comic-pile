import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ContinuityPlannerPage from '../pages/ContinuityPlannerPage'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  update: vi.fn(),
  readiness: vi.fn(),
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
    readiness: mocks.readiness,
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

const secondThread = {
  ...thread,
  id: 5,
  title: 'New Gods',
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

const secondIssue = {
  id: 41,
  thread_id: 5,
  issue_number: '7',
  position: 7,
  status: 'unread',
  read_at: null,
  created_at: '2026-08-12T00:00:00Z',
}

beforeEach(() => {
  window.localStorage.clear()
  mocks.get.mockReset()
  mocks.create.mockReset()
  mocks.update.mockReset()
  mocks.readiness.mockReset()
  mocks.readiness.mockResolvedValue({
    plan_id: 12,
    plan_name: 'Saved lane',
    ordering_mode: 'strict_sequential',
    lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
    nodes: [],
    plan_diagnostics: [],
    summary: { total: 0, readable: 0, blocked: 0, complete: 0, unavailable: 0 },
    generated_at: '2026-08-12T00:00:00Z',
  })
  mocks.listIssues.mockReset()
  mocks.listThreads.mockResolvedValue({ threads: [thread, secondThread], next_page_token: null })
  mocks.listGroups.mockResolvedValue([{ id: 8, name: 'Fourth World', memberships: [], created_at: '2026-08-12T00:00:00Z' }])
  mocks.listIssues.mockResolvedValue({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
  mocks.getIssue.mockResolvedValue(issue)
  mocks.getThread.mockResolvedValue(thread)
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
  mocks.update.mockResolvedValue({
    id: 12,
    user_id: 1,
    name: 'Saved lane',
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
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
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
      nodes: [{ id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 0 , label: 'Fourth World'}],
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

    expect(await screen.findByRole('button', { name: 'Remove Fourth World' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Remove Fourth World' }))
    expect(screen.getByText('Unsaved changes')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(screen.getByRole('button', { name: 'Remove Fourth World' })).toBeVisible()
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it('moves a node up and down using the lane reorder controls', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
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

    // Initially first item is "Mister Miracle #Annual 1" at position 1
    await waitFor(() => expect(screen.getByText('Mister Miracle #Annual 1')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('lane-item-0')).toHaveTextContent('Mister Miracle #Annual 1'))
    await waitFor(() => expect(screen.getByTestId('lane-item-1')).toHaveTextContent('Fourth World'))

    const moveDownButton = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await act(async () => {
      await user.click(moveDownButton)
    })
    // After moving down, the order should be swapped
    const firstItem = screen.getByTestId('lane-item-0')
    const secondItem = screen.getByTestId('lane-item-1')
    expect(firstItem).toHaveTextContent('Fourth World')
    expect(secondItem).toHaveTextContent('Mister Miracle #Annual 1')

    const moveUpButton = screen.getByRole('button', { name: /Move Mister Miracle #Annual 1 earlier/i })
    await act(async () => {
      await user.click(moveUpButton)
    })
    // After moving up, the order should be restored
    const restoredFirstItem = screen.getByTestId('lane-item-0')
    const restoredSecondItem = screen.getByTestId('lane-item-1')
    expect(restoredFirstItem).toHaveTextContent('Mister Miracle #Annual 1')
    expect(restoredSecondItem).toHaveTextContent('Fourth World')
  })

  it('reopens the last saved plan when the local-storage marker exists', async () => {
    window.localStorage.setItem('comic-pile:last-continuity-plan', '12')
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const reopen = await screen.findByRole('button', { name: 'Reopen last saved plan' })
    await user.click(reopen)
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(12))
  })

  it('ignores stale issue requests when the user switches thread selections', async () => {
    let resolveFirst!: (value: { issues: typeof issue[]; total_count: number; page_size: number; next_page_token: null }) => void
    const firstList = new Promise<{ issues: typeof issue[]; total_count: number; page_size: number; next_page_token: null }>((resolve) => {
      resolveFirst = resolve
    })
    mocks.listIssues
      .mockImplementationOnce(() => firstList)
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: null })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await user.clear(screen.getByLabelText('Comic series'))
    await user.type(screen.getByLabelText('Comic series'), 'New');
    await user.click(screen.getByRole('option', { name: /New Gods/i }))
    await screen.findByRole('option', { name: /#7$/ })
    resolveFirst({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
    await waitFor(() => expect(screen.queryByRole('option', { name: /#Annual 1$/ })).not.toBeInTheDocument())
  })

  it('shows an inline error when loading issues for the selected comic fails', async () => {
    mocks.listIssues.mockReset()
    mocks.listIssues.mockRejectedValueOnce(new Error('network down'))

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/network down/i)
  })

  it('surfaces a save error without discarding the in-progress plan', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { code: 'plan_rule_conflict' } } },
    })

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
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/conflicts with an existing continuity rule/i)
  })

  it('surfaces a cycle error when the API rejects with the continuity_cycle code', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { code: 'continuity_cycle' } } },
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/continuity cycle/i)
  })

  it('shows an error for a non-numeric route id', async () => {
    render(
      <MemoryRouter initialEntries={['/continuity-plans/not-a-number']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid continuity plan ID/i)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('shows an error for a zero route id', async () => {
    render(
      <MemoryRouter initialEntries={['/continuity-plans/0']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid continuity plan ID/i)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('shows an error for a negative route id', async () => {
    render(
      <MemoryRouter initialEntries={['/continuity-plans/-1']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Invalid continuity plan ID/i)
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('updates an existing plan with the in-memory node order', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
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

    const moveDown = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await user.click(moveDown)
    await user.click(screen.getByRole('button', { name: 'Save plan' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    expect(mocks.update).toHaveBeenCalledWith(12, expect.objectContaining({
      nodes: [
        expect.objectContaining({ id: 'crossover-8', position: 0 }),
        expect.objectContaining({ id: 'issue-40', position: 1 }),
      ],
    }))
  })

  it('falls back to the default name when canceling an unsaved new plan', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const nameInput = await screen.findByLabelText('Plan name')
    await user.clear(nameInput)
    await user.type(nameInput, 'Temporary name')
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(screen.getByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(screen.getByLabelText('Plan name')).toHaveValue('My reading plan')
  })

  it('rejects adding the same issue or crossover twice and surfaces an inline error', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/already in this plan/i)

    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/already in this plan/i)
  })

  it('requires a non-empty plan name before save', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const nameInput = await screen.findByLabelText('Plan name')
    await user.clear(nameInput)
    await user.type(nameInput, '   ')
    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter a plan name\./i)
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('falls back to a deleted-series label when an issue has no persisted title', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [{ id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'}],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.getIssue.mockReset()

    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Mister Miracle #Annual 1')).toBeVisible()
    expect(mocks.getIssue).not.toHaveBeenCalled()
  })

  it('renders a deleted-crossover label when the saved crossover is missing from the current group list', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [{ id: 'crossover-99', node_type: 'crossover', ref_id: 99, lane_id: 'main', position: 0 , label: 'Missing crossover'}],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Missing crossover')).toBeVisible()
  })

  it('shows a plan-level load error when fetching the plan fails', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Cannot read plan'))

    render(
      <MemoryRouter initialEntries={['/continuity-plans/12']}>
        <Routes>
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/Cannot read plan/i)
  })

  it('uses the API detail string when the save error payload includes one', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: 'Backend rejected the plan.' } },
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Backend rejected the plan\./i)
  })

  it('falls back to the thrown error message when the save error has no axios detail', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce(new Error('Boom'))

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Boom/i)
  })

  it('pages through threads across multiple tokenized responses', async () => {
    mocks.listThreads.mockReset()
    mocks.listThreads
      .mockResolvedValueOnce({ threads: [thread], next_page_token: 'page-2' })
      .mockResolvedValueOnce({ threads: [secondThread], next_page_token: null })
    mocks.listIssues.mockReset()
    mocks.listIssues
      .mockResolvedValueOnce({ issues: [issue], total_count: 1, page_size: 100, next_page_token: 'issues-2' })
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: null })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(mocks.listThreads).toHaveBeenCalledTimes(2))
    await user.type(screen.getByLabelText('Comic series'), 'New');
    expect(await screen.findByRole('option', { name: /New Gods/i })).toBeVisible()
    await user.click(screen.getByRole('option', { name: /New Gods/i }))
    await screen.findByRole('option', { name: /#7$/ })
  })

  it('disables move controls at lane boundaries and removes nodes', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
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

    expect(await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 earlier/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Move Fourth World later/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Remove Fourth World' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
  })

  it('moves the first node down and back up, preserving order', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
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

    const moveDownButton = await screen.findByRole('button', { name: /Move Mister Miracle #Annual 1 later/i })
    await user.click(moveDownButton)
    await waitFor(() => expect(screen.getByText('2')).toBeVisible())
    const moveUpButton = screen.getByRole('button', { name: /Move Mister Miracle #Annual 1 earlier/i })
    await user.click(moveUpButton)
    await waitFor(() => expect(screen.getByText('1')).toBeVisible())
  })

  it('ignores the create form when the user has not selected an issue', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const addIssueButton = await screen.findByRole('button', { name: 'Add issue' })
    expect(addIssueButton).toBeDisabled()
    await user.click(addIssueButton)
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('ignores the add-crossover click when no crossover is selected', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const addCrossoverButton = await screen.findByRole('button', { name: 'Add crossover' })
    expect(addCrossoverButton).toBeDisabled()
    await user.click(addCrossoverButton)
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('breaks the pagination loop when the API repeats the same next_page_token', async () => {
    mocks.listThreads.mockReset()
    mocks.listThreads
      .mockResolvedValueOnce({ threads: [thread], next_page_token: 'duplicate' })
      .mockResolvedValueOnce({ threads: [secondThread], next_page_token: 'duplicate' })

    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(mocks.listThreads).toHaveBeenCalledTimes(2))
  })

  it('falls back to the default plan name when canceling an unsaved new plan without typing a name', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    expect(screen.getByLabelText('Plan name')).toHaveValue('My reading plan')
  })

  it('falls back to the generic save message when the rejection is neither an axios detail nor an Error', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({ code: 500 })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to save this continuity plan\./i)
  })

  it('breaks the issue pagination loop when the API repeats the same next_page_token', async () => {
    mocks.listIssues.mockReset()
    mocks.listIssues
      .mockResolvedValueOnce({ issues: [issue], total_count: 1, page_size: 100, next_page_token: 'repeat' })
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: 'repeat' })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await waitFor(() => expect(mocks.listIssues).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not surface an error from an issue request that was aborted by a thread switch', async () => {
    mocks.listIssues.mockReset()
    mocks.listIssues
      .mockImplementationOnce(() => Promise.reject(new Error('stale failure')))
      .mockResolvedValueOnce({ issues: [secondIssue], total_count: 1, page_size: 100, next_page_token: null })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await user.clear(screen.getByLabelText('Comic series'))
    await user.type(screen.getByLabelText('Comic series'), 'New');
    await user.click(screen.getByRole('option', { name: /New Gods/i }))
    await screen.findByRole('option', { name: /#7$/ })
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('ignores plan hydration that resolves after the page has unmounted', async () => {
    let resolveThreads!: (value: { threads: typeof thread[]; next_page_token: string | null }) => void
    mocks.listThreads.mockReset()
    mocks.listThreads.mockImplementationOnce(() => new Promise((resolve) => {
      resolveThreads = resolve
    }))

    const { unmount } = render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    unmount()
    resolveThreads({ threads: [thread], next_page_token: null })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(mocks.get).not.toHaveBeenCalled()
  })

  it('falls back to the generic save message when the API detail is an object without a known code', async () => {
    mocks.create.mockReset()
    mocks.create.mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: { problem: 'wrapped failure' } } },
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to save this continuity plan\./i)
  })

  it('restores the default plan name when canceling before the initial name has loaded', async () => {
    mocks.listThreads.mockReset()
    mocks.listThreads.mockImplementationOnce(() => new Promise(() => {}))

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const cancelButton = await screen.findByRole('button', { name: 'Cancel changes' })
    await user.click(cancelButton)
    expect(screen.getByLabelText('Plan name')).toHaveValue('My reading plan')
  })

  it('saves two parallel lanes after moving a node across lanes', async () => {
    mocks.create.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'lane-1', name: 'Lane 2', order: 1 },
      ],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'lane-1', position: 0 , label: 'Fourth World'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/continuity-plans']}>
        <Routes>
          <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
          <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('Comic series'), 'Mister');
    await user.click(await screen.findByRole('option', { name: /Mister Miracle/i }))
    await screen.findByRole('option', { name: /Annual 1/i })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))

    await user.click(screen.getByRole('button', { name: 'Add lane' }))

    await user.selectOptions(
      screen.getByRole('combobox', { name: /Move Fourth World to another lane/i }),
      'lane-1',
    )

    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())

    const payload = mocks.create.mock.calls[0][0] as {
      ordering_mode: string
      lanes: Array<{ id: string }>
      nodes: Array<{ id: string; lane_id: string; position: number }>
    }
    expect(payload.ordering_mode).toBe('informational')
    expect(payload.lanes.map((lane) => lane.id)).toEqual(['main', 'lane-1'])
    expect(payload.nodes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: 'issue-40', lane_id: 'main', position: 0 }),
        expect.objectContaining({ id: 'crossover-8', lane_id: 'lane-1', position: 0 }),
      ]),
    )
  })

  it('disables removing a non-empty lane and enables it once emptied', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Reading order', order: 0 },
        { id: 'lane-2', name: 'Lane 2', order: 1 },
      ],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Parallel plan',
      ordering_mode: 'informational',
      lanes: [{ id: 'main', name: 'Reading order', order: 0 }],
      nodes: [
        { id: 'issue-40', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #Annual 1'},
        { id: 'crossover-8', node_type: 'crossover', ref_id: 8, lane_id: 'main', position: 1 , label: 'Fourth World'},
      ],
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

    const removeMain = await screen.findByRole('button', { name: 'Remove lane Reading order' })
    expect(removeMain).toBeDisabled()
    const removeLane2 = screen.getByRole('button', { name: 'Remove lane Lane 2' })
    expect(removeLane2).toBeEnabled()

    // Move both steps into the second lane, then empty and remove it.
    await user.selectOptions(
      screen.getByRole('combobox', { name: /Move Mister Miracle #Annual 1 to another lane/i }),
      'lane-2',
    )
    await user.selectOptions(
      screen.getByRole('combobox', { name: /Move Fourth World to another lane/i }),
      'lane-2',
    )

    expect(screen.getByRole('button', { name: 'Remove lane Lane 2' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Remove lane Reading order' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Remove lane Reading order' }))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    const payload = mocks.update.mock.calls[0][1] as {
      lanes: Array<{ id: string }>
      nodes: Array<{ id: string; lane_id: string }>
    }
    expect(payload.lanes.map((lane) => lane.id)).toEqual(['lane-2'])
    expect(payload.nodes.every((node) => node.lane_id === 'lane-2')).toBe(true)
  })

  it('toggles checkpoint on a node and persists it on save', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Checkpoint plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'a-2', node_type: 'issue', ref_id: 41, lane_id: 'main', position: 1 , label: 'Mister Miracle #2'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Checkpoint plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'a-2', node_type: 'issue', ref_id: 41, lane_id: 'main', position: 1 , label: 'Mister Miracle #2', is_checkpoint: true, convergence_gate: [] },
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1'},
      ],
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

    await waitFor(() => expect(screen.getByText('Mister Miracle #2')).toBeVisible())

    // Toggle checkpoint on the second node
    const checkpointButton = screen.getByRole('button', { name: /Mark Mister Miracle #2 as checkpoint/i })
    await user.click(checkpointButton)

    // Verify checkpoint badge appears
    expect(screen.getByText('Checkpoint')).toBeVisible()

    // Save and verify the checkpoint is included
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    const payload = mocks.update.mock.calls[0][1] as { nodes: Array<{ id: string; is_checkpoint?: boolean }> }
    const checkpointNode = payload.nodes.find((n) => n.id === 'a-2')
    expect(checkpointNode?.is_checkpoint).toBe(true)
  })

  it('opens convergence editor, adds a gate target, closes editor, and saves', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1'},
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1', is_checkpoint: false, convergence_gate: [{ node_type: 'issue', node_id: 'a-1' }] },
      ],
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

    await waitFor(() => expect(screen.getByText('New Gods #1')).toBeVisible())

    // Open convergence editor for the second node
    const convergenceButton = screen.getByRole('button', { name: /Edit convergence gate for New Gods #1/i })
    await user.click(convergenceButton)

    // Verify convergence editor is open
    expect(screen.getByTestId('convergence-editor-b-1')).toBeVisible()

    // Select the first node as a convergence target
    const checkbox = screen.getByRole('checkbox', { name: /Mister Miracle #1/i })
    await user.click(checkbox)

    // Close the editor
    await user.click(screen.getByRole('button', { name: 'Done' }))

    // Verify convergence badge appears
    expect(screen.getByText('Convergence (1)')).toBeVisible()

    // Save and verify the convergence gate is included
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    const payload = mocks.update.mock.calls[0][1] as { nodes: Array<{ id: string; convergence_gate?: Array<{ node_id: string }> }> }
    const convergenceNode = payload.nodes.find((n) => n.id === 'b-1')
    expect(convergenceNode?.convergence_gate).toHaveLength(1)
    expect(convergenceNode?.convergence_gate?.[0].node_id).toBe('a-1')
  })

  it('removes a convergence gate target and saves', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1', is_checkpoint: false, convergence_gate: [{ node_type: 'issue', node_id: 'a-1' }] },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.update.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Convergence plan',
      ordering_mode: 'informational',
      lanes: [
        { id: 'main', name: 'Lane A', order: 0 },
        { id: 'lane-b', name: 'Lane B', order: 1 },
      ],
      nodes: [
        { id: 'a-1', node_type: 'issue', ref_id: 40, lane_id: 'main', position: 0 , label: 'Mister Miracle #1'},
        { id: 'b-1', node_type: 'issue', ref_id: 42, lane_id: 'lane-b', position: 0 , label: 'New Gods #1', is_checkpoint: false, convergence_gate: [] },
      ],
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

    await waitFor(() => expect(screen.getByText('Convergence (1)')).toBeVisible())

    // Open convergence editor for the second node
    const convergenceButton = screen.getByRole('button', { name: /Edit convergence gate for New Gods #1/i })
    await user.click(convergenceButton)

    // Unselect the first node
    const checkbox = screen.getByRole('checkbox', { name: /Mister Miracle #1/i })
    await user.click(checkbox)

    // Close the editor
    await user.click(screen.getByRole('button', { name: 'Done' }))

    // Verify convergence badge is gone
    expect(screen.queryByText('Convergence')).not.toBeInTheDocument()

    // Save and verify the convergence gate is removed
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())

    const payload = mocks.update.mock.calls[0][1] as { nodes: Array<{ id: string; convergence_gate?: Array<{ node_id: string }> }> }
    const convergenceNode = payload.nodes.find((n) => n.id === 'b-1')
    expect(convergenceNode?.convergence_gate).toHaveLength(0)
  })
})
