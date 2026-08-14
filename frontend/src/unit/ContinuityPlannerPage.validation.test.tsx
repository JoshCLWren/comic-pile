import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  dependencyGroupsApi: {
    list: mocks.listGroups,
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: mocks.listIssues,
    get: mocks.getIssue,
  },
}))

vi.mock('../services/api', () => ({
  threadsApi: {
    list: mocks.listThreads,
    get: mocks.getThread,
  },
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

const threadB = {
  ...thread,
  id: 9,
  title: 'Mister Miracle Annual',
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

const emptyPage = { threads: [], next_page_token: null }

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function renderCreate() {
  return render(
    <MemoryRouter initialEntries={['/continuity-plans']}>
      <Routes>
        <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
        <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function renderEdit() {
  return render(
    <MemoryRouter initialEntries={['/continuity-plans/12']}>
      <Routes>
        <Route path="/continuity-plans" element={<ContinuityPlannerPage />} />
        <Route path="/continuity-plans/:id" element={<ContinuityPlannerPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function clickThreadOption(user: ReturnType<typeof userEvent.setup>, title: string) {
  const listbox = await screen.findByRole('listbox', { name: 'Comic series results' })
  const option = within(listbox).getByText(title).closest('button')
  if (!option) throw new Error(`Thread option ${title} not found`)
  await user.click(option)
}

async function selectFirstThread(user: ReturnType<typeof userEvent.setup>) {
  await clickThreadOption(user, 'Mister Miracle')
}

beforeEach(() => {
  window.localStorage.clear()
  mocks.listThreads.mockReset().mockResolvedValue({ threads: [thread], next_page_token: null })
  mocks.listGroups.mockReset().mockResolvedValue([
    { id: 8, name: 'Fourth World', memberships: [], created_at: '2026-08-12T00:00:00Z' },
  ])
  mocks.listIssues.mockReset().mockResolvedValue({
    issues: [issue],
    total_count: 1,
    page_size: 100,
    next_page_token: null,
  })
  mocks.getIssue.mockReset().mockResolvedValue(issue)
  mocks.getThread.mockReset().mockResolvedValue(thread)
  mocks.create.mockReset().mockResolvedValue({
    id: 12,
    user_id: 1,
    name: 'Kirby lane',
    ordering_mode: 'strict_sequential',
    nodes: [],
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  })
  mocks.get.mockReset().mockResolvedValue({
    id: 12,
    user_id: 1,
    name: 'Saved lane',
    ordering_mode: 'strict_sequential',
    nodes: [],
    created_at: '2026-08-12T00:00:00Z',
    updated_at: '2026-08-12T00:00:00Z',
  })
  mocks.update.mockReset()
})

describe('ContinuityPlannerPage save and load errors', () => {
  async function attemptSaveWith(rejection: unknown) {
    mocks.create.mockRejectedValue(rejection)
    const user = userEvent.setup()
    renderCreate()
    await user.clear(await screen.findByLabelText('Plan name'))
    await user.type(screen.getByLabelText('Plan name'), 'Kirby lane')
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
    return screen.getByRole('alert')
  }

  it('surfaces string detail messages from the API', async () => {
    const alert = await attemptSaveWith({
      isAxiosError: true,
      response: { data: { detail: 'That name is already taken' } },
    })
    expect(alert.textContent).toBe('That name is already taken')
  })

  it('explains plan rule conflicts with a friendly message', async () => {
    const alert = await attemptSaveWith({
      isAxiosError: true,
      response: { data: { detail: { code: 'plan_rule_conflict' } } },
    })
    expect(alert.textContent).toContain('conflicts with an existing continuity rule')
  })

  it('explains continuity cycles with a friendly message', async () => {
    const alert = await attemptSaveWith({
      isAxiosError: true,
      response: { data: { detail: { code: 'continuity_cycle' } } },
    })
    expect(alert.textContent).toContain('would create a continuity cycle')
  })

  it('falls back for unknown error codes', async () => {
    const alert = await attemptSaveWith({
      isAxiosError: true,
      response: { data: { detail: { code: 'something_else' } } },
    })
    expect(alert.textContent).toBe('Unable to save this continuity plan.')
  })

  it('falls back for non-object detail payloads', async () => {
    const alert = await attemptSaveWith({
      isAxiosError: true,
      response: { data: { detail: 5 } },
    })
    expect(alert.textContent).toBe('Unable to save this continuity plan.')
  })

  it('falls back when the response carries no detail payload', async () => {
    const alert = await attemptSaveWith({ isAxiosError: true, message: 'Network Error' })
    expect(alert.textContent).toBe('Unable to save this continuity plan.')
  })

  it('uses plain Error messages as a last resort', async () => {
    const alert = await attemptSaveWith(new Error('server exploded'))
    expect(alert.textContent).toBe('server exploded')
  })

  it('hides the status indicator while a failed save is shown', async () => {
    await attemptSaveWith({
      isAxiosError: true,
      response: { data: { detail: { code: 'plan_rule_conflict' } } },
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('requires a plan name before saving', async () => {
    const user = userEvent.setup()
    renderCreate()
    await user.clear(await screen.findByLabelText('Plan name'))
    await user.click(screen.getByRole('button', { name: 'Save plan' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe('Enter a plan name.')
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('renders load failures for an existing plan', async () => {
    mocks.get.mockRejectedValue(new Error('load failed'))
    renderEdit()
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe('load failed')
  })
})

describe('ContinuityPlannerPage pagination', () => {
  it('loads every thread page and stops on a repeated token', async () => {
    mocks.listThreads
      .mockResolvedValueOnce({ threads: [thread], next_page_token: 'page-2' })
      .mockResolvedValueOnce({ threads: [threadB], next_page_token: 'page-2' })
    renderCreate()
    await waitFor(() => expect(mocks.listThreads).toHaveBeenCalledTimes(2))
    expect(mocks.listThreads).toHaveBeenNthCalledWith(1, { page_size: 100 }, null)
    expect(mocks.listThreads).toHaveBeenNthCalledWith(2, { page_size: 100 }, 'page-2')
    expect(
      within(screen.getByRole('listbox', { name: 'Comic series results' })).getByText(
        'Mister Miracle Annual',
      ),
    ).toBeVisible()
  })

  it('loads every issue page with page tokens', async () => {
    mocks.listIssues
      .mockReset()
      .mockResolvedValueOnce({
        issues: [issue],
        total_count: 1,
        page_size: 100,
        next_page_token: 'more',
      })
      .mockResolvedValueOnce({
        issues: [issue],
        total_count: 1,
        page_size: 100,
        next_page_token: 'more',
      })
    const user = userEvent.setup()
    renderCreate()
    await selectFirstThread(user)
    await waitFor(() => expect(mocks.listIssues).toHaveBeenCalledTimes(2))
    expect(mocks.listIssues).toHaveBeenNthCalledWith(1, 4, { page_size: 100 }, expect.any(AbortSignal))
    expect(mocks.listIssues).toHaveBeenNthCalledWith(2, 4, {
      page_size: 100,
      page_token: 'more',
    }, expect.any(AbortSignal))
  })
})

describe('ContinuityPlannerPage selection edge cases', () => {
  it('clears the selected thread when the search query diverges from its title', async () => {
    const user = userEvent.setup()
    renderCreate()
    await selectFirstThread(user)
    await screen.findByLabelText('Issue')
    await user.type(screen.getByPlaceholderText('Search by title'), 'x')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Add issue' })).toBeDisabled(),
    )
    expect(mocks.listIssues).toHaveBeenCalledOnce()
  })

  it('ignores a blank issue selection when the add-issue form submits', async () => {
    renderCreate()
    fireEvent.submit(screen.getByRole('form', { name: 'Add an issue' }))
    expect(mocks.create).not.toHaveBeenCalled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('rejects duplicate issues', async () => {
    const user = userEvent.setup()
    renderCreate()
    await selectFirstThread(user)
    await screen.findByRole('option', { name: '#Annual 1' })
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    await user.selectOptions(screen.getByLabelText('Issue'), '40')
    await user.click(screen.getByRole('button', { name: 'Add issue' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe('That issue is already in this plan.')
  })

  it('rejects duplicate crossovers', async () => {
    const user = userEvent.setup()
    renderCreate()
    await user.selectOptions(await screen.findByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    await user.selectOptions(screen.getByLabelText('Crossover'), '8')
    await user.click(screen.getByRole('button', { name: 'Add crossover' }))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe('That crossover is already in this plan.')
  })
})

describe('ContinuityPlannerPage issue loading lifecycle', () => {
  it('ignores stale issue responses after switching threads', async () => {
    const first = deferred<{ issues: typeof issue[]; total_count: number; page_size: number; next_page_token: string | null }>()
    const second = deferred<{ issues: typeof issue[]; total_count: number; page_size: number; next_page_token: string | null }>()
    mocks.listIssues.mockReset().mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise)
    mocks.listThreads.mockResolvedValue({ threads: [thread, threadB], next_page_token: null })

    const user = userEvent.setup()
    renderCreate()
    await clickThreadOption(user, 'Mister Miracle')
    await clickThreadOption(user, 'Mister Miracle Annual')

    first.resolve({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })
    await act(async () => {})
    second.resolve({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })

    await screen.findByRole('option', { name: '#Annual 1' })
    expect(mocks.listIssues).toHaveBeenCalledTimes(2)
  })

  it('ignores stale issue rejections after switching threads', async () => {
    const first = deferred<{ issues: typeof issue[]; total_count: number; page_size: number; next_page_token: string | null }>()
    const second = deferred<{ issues: typeof issue[]; total_count: number; page_size: number; next_page_token: string | null }>()
    mocks.listIssues.mockReset().mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise)
    mocks.listThreads.mockResolvedValue({ threads: [thread, threadB], next_page_token: null })

    const user = userEvent.setup()
    renderCreate()
    await clickThreadOption(user, 'Mister Miracle')
    await clickThreadOption(user, 'Mister Miracle Annual')

    first.reject(new Error('stale'))
    await act(async () => {})
    second.resolve({ issues: [issue], total_count: 1, page_size: 100, next_page_token: null })

    await screen.findByRole('option', { name: '#Annual 1' })
    expect(mocks.listIssues).toHaveBeenCalledTimes(2)
  })

  it('reports issue loading failures', async () => {
    mocks.listIssues.mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    renderCreate()
    await selectFirstThread(user)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toBe('boom')
  })
})

describe('ContinuityPlannerPage hydration and lifecycle', () => {
  it('labels missing crossovers and issues as unavailable', async () => {
    mocks.get.mockResolvedValue({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        {
          id: 'crossover-99',
          node_type: 'crossover',
          ref_id: 99,
          lane_id: 'main',
          position: 0,
        },
        {
          id: 'issue-999',
          node_type: 'issue',
          ref_id: 999,
          lane_id: 'main',
          position: 1,
        },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    mocks.getIssue.mockRejectedValue(new Error('gone'))
    renderEdit()
    expect(await screen.findByText('Unavailable crossover')).toBeVisible()
    expect(screen.getByText('Unavailable issue')).toBeVisible()
  })

  it('ignores loads that finish after unmounting on the create page', async () => {
    const { unmount } = renderCreate()
    await act(async () => {
      unmount()
    })
    expect(mocks.listThreads).toHaveBeenCalledOnce()
  })

  it('ignores hydration that finishes after unmounting an existing plan', async () => {
    const pending = deferred<unknown>()
    mocks.get.mockReturnValue(pending.promise)
    const { unmount } = renderEdit()
    await waitFor(() => expect(mocks.get).toHaveBeenCalledOnce())
    unmount()
    pending.resolve({
      id: 12,
      user_id: 1,
      name: 'Saved lane',
      ordering_mode: 'strict_sequential',
      nodes: [
        {
          id: 'issue-40',
          node_type: 'issue',
          ref_id: 40,
          lane_id: 'main',
          position: 0,
        },
      ],
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    })
    await act(async () => {})
    expect(mocks.getIssue).toHaveBeenCalledOnce()
  })

  it('restores the default name when canceling a brand-new plan', async () => {
    const pending = deferred<typeof emptyPage>()
    mocks.listThreads.mockReturnValue(pending.promise)
    const user = userEvent.setup()
    renderCreate()
    await user.click(screen.getByRole('button', { name: 'Cancel changes' }))
    pending.resolve(emptyPage)
    await act(async () => {})
    expect(screen.getByLabelText('Plan name')).toHaveValue('My reading plan')
  })

  it('offers to reopen the last saved plan on the create page', async () => {
    window.localStorage.setItem('comic-pile:last-continuity-plan', '12')
    renderCreate()
    expect(await screen.findByRole('button', { name: 'Reopen last saved plan' })).toBeVisible()
  })
})
