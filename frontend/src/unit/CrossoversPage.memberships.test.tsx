import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { threadsApi } from '../services/api'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'

vi.mock('../services/api', () => ({
  threadsApi: {
    list: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
  },
}))

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    delete: vi.fn(),
    addMember: vi.fn(),
    addIssueRange: vi.fn(),
    removeMember: vi.fn(),
  },
}))

const api = vi.mocked(dependencyGroupsApi)
const threadApi = vi.mocked(threadsApi)
const issueApi = vi.mocked(issuesApi)

function renderPage() {
  return render(
    <MemoryRouter>
      <CrossoversPage />
    </MemoryRouter>,
  )
}

const crossover = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [
    { id: 1, issue_id: 31, thread_id: null, series_title: 'Nova', issue_number: '2' },
    { id: 2, issue_id: null, thread_id: 22, series_title: 'Nova', issue_number: null },
  ],
}

const thread = {
  id: 22,
  title: 'Nova',
  format: 'single issues',
  issues_remaining: 3,
  total_issues: 3,
  queue_position: 4,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-08-01T00:00:00Z',
}

const xmenThread = {
  ...thread,
  id: 44,
  title: 'Uncanny X-Men',
  queue_position: 8,
}

const issues = [
  {
    id: 31,
    thread_id: 22,
    issue_number: '2',
    position: 3,
    status: 'read' as const,
    read_at: '2026-08-02T00:00:00Z',
    created_at: '2026-08-01T00:00:00Z',
  },
  {
    id: 32,
    thread_id: 22,
    issue_number: 'Annual 1',
    position: 4,
    status: 'unread' as const,
    read_at: null,
    created_at: '2026-08-01T00:00:00Z',
  },
  {
    id: 33,
    thread_id: 22,
    issue_number: '½',
    position: 5,
    status: 'unread' as const,
    read_at: null,
    created_at: '2026-08-01T00:00:00Z',
  },
]

function selectThread(label: string, query: string, title: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value: query } })
  const listbox = screen.getByRole('listbox', { name: `${label} results` })
  fireEvent.click(within(listbox).getByRole('option', { name: new RegExp(title) }))
}

beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue([crossover])
  threadApi.list.mockResolvedValue({
    threads: [thread, xmenThread],
    next_page_token: null,
  })
  issueApi.list.mockResolvedValue({
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: null,
  })
})

describe('CrossoversPage membership editing', () => {
  it('shows individual issue and thread memberships with real comic metadata', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    expect(screen.getByText('Nova #2')).toBeInTheDocument()
    expect(screen.getByText('Nova (whole series)')).toBeInTheDocument()
    expect(screen.queryByText(/Issue \d+/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Thread \d+/)).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Annihilation members' })).toBeInTheDocument()
  })

  it('renders a readable fallback when member metadata cannot be resolved', async () => {
    api.list.mockResolvedValue([{
      ...crossover,
      memberships: [{ id: 9, issue_id: 99, thread_id: null, series_title: null, issue_number: null }],
    }])
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*1 member/ }))

    expect(screen.getByText('Unavailable comic')).toBeInTheDocument()
    expect(screen.queryByText(/Issue \d+/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Thread \d+/)).not.toBeInTheDocument()
  })

  it('adds a whole thread from the shared human-facing selector', async () => {
    api.addMember.mockResolvedValue({ id: 3, issue_id: null, thread_id: 44, series_title: 'Uncanny X-Men', issue_number: null })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    selectThread('Current thread of series', 'uncanny', 'Uncanny X-Men')
    expect(screen.getByLabelText('Current thread of series')).toHaveValue('Uncanny X-Men')

    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))

    expect(await screen.findByText('Uncanny X-Men (whole series)')).toBeInTheDocument()
    expect(api.addMember).toHaveBeenCalledWith(7, { thread_id: 44 })
    expect(screen.getByRole('status')).toHaveTextContent('Uncanny X-Men added to crossover as 1 thread member.')
  })

  it('preserves unrelated crossovers while adding and removing memberships', async () => {
    const unrelated = {
      id: 8,
      name: 'Secret Invasion',
      created_at: '2026-08-06T00:00:00Z',
      memberships: [{ id: 8, issue_id: 80, thread_id: null, series_title: 'Mighty Avengers', issue_number: '12' }],
    }
    api.list.mockResolvedValue([crossover, unrelated])
    api.addMember.mockResolvedValue({ id: 3, issue_id: null, thread_id: 44, series_title: 'Uncanny X-Men', issue_number: null })
    api.removeMember.mockResolvedValue(undefined)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))
    selectThread('Current thread of series', 'uncanny', 'Uncanny X-Men')
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))
    expect(await screen.findByText('Uncanny X-Men (whole series)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Remove Nova #2 from Annihilation' }))
    await waitFor(() => expect(screen.queryByText('Nova #2')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Secret Invasion.*1 member/ })).toBeInTheDocument()
  })

  it('adds an issue range after selecting a series by title', async () => {
    api.addIssueRange.mockResolvedValue({
      thread_id: 22,
      start_position: 3,
      end_position: 5,
      added_issue_ids: [31],
      already_present_issue_ids: [],
    })
    api.get.mockResolvedValue(crossover)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    selectThread('Comic series for issue range', 'Nova', 'Nova')
    await screen.findByText(/Issues from Nova/)
    fireEvent.change(screen.getByLabelText('First issue'), { target: { value: '31' } })
    fireEvent.change(screen.getByLabelText('Last issue'), { target: { value: '33' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    await waitFor(() => expect(api.addIssueRange).toHaveBeenCalledWith(7, 22, 3, 5))
  })

  it('keeps a successful range add committed when the membership refresh fails', async () => {
    api.addIssueRange.mockResolvedValue({
      thread_id: 22,
      start_position: 3,
      end_position: 5,
      added_issue_ids: [31],
      already_present_issue_ids: [],
    })
    api.get.mockRejectedValue(new Error('Refresh unavailable'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    selectThread('Comic series for issue range', 'Nova', 'Nova')
    await screen.findByLabelText('First issue')
    fireEvent.change(screen.getByLabelText('First issue'), { target: { value: '31' } })
    fireEvent.change(screen.getByLabelText('Last issue'), { target: { value: '33' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('1 added, 0 already present.')
    expect(status).toHaveTextContent('latest memberships could not be refreshed: Refresh unavailable')
    expect(api.addIssueRange).toHaveBeenCalledWith(7, 22, 3, 5)
  })

  it('keeps the selected series when adding a whole-thread membership fails', async () => {
    api.addMember.mockRejectedValue(new Error('Thread lookup unavailable'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    selectThread('Current thread of series', 'uncanny', 'Uncanny X-Men')
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Thread lookup unavailable')
    expect(screen.getByLabelText('Current thread of series')).toHaveValue('Uncanny X-Men')
    expect(screen.getByRole('button', { name: 'Add thread' })).toBeEnabled()
  })

  it('never exposes raw thread ID inputs in crossover membership forms', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    expect(screen.queryByLabelText('Whole thread ID')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Thread ID')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Current thread of series')).toHaveAttribute('type', 'search')
    expect(screen.getByLabelText('Comic series for issue range')).toHaveAttribute('type', 'search')
  })

  it('shows a useful selector error when comics cannot be loaded', async () => {
    threadApi.list.mockRejectedValue(new Error('Comics unavailable'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    expect(await screen.findAllByRole('alert')).toEqual(expect.arrayContaining([
      expect.objectContaining({ textContent: 'Comics unavailable' }),
    ]))
  })

  it('removes a membership without changing the crossover itself', async () => {
    api.removeMember.mockResolvedValue(undefined)
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove Nova #2 from Annihilation' }))
    await waitFor(() => expect(screen.queryByText('Nova #2')).not.toBeInTheDocument())
    expect(api.removeMember).toHaveBeenCalledWith(7, 1)
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Comic removed from crossover.')
  })

  it('ignores another membership removal while one is pending', async () => {
    let resolveRemoval: (() => void) | undefined
    api.removeMember.mockImplementation(() => new Promise<void>((resolve) => {
      resolveRemoval = resolve
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove Nova #2 from Annihilation' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Nova (whole series) from Annihilation' }))
    expect(api.removeMember).toHaveBeenCalledTimes(1)
    resolveRemoval?.()
    await waitFor(() => expect(screen.queryByText('Nova #2')).not.toBeInTheDocument())
    expect(screen.getByText('Nova (whole series)')).toBeInTheDocument()
  })

  it('keeps membership visible when removal fails', async () => {
    api.removeMember.mockRejectedValue(new Error('Removal unavailable'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Nova #2 from Annihilation' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Removal unavailable')
    expect(screen.getByText('Nova #2')).toBeInTheDocument()
  })

  it('honestly labels the series thread addition and reports one thread member created', async () => {
    api.addMember.mockResolvedValue({ id: 3, issue_id: null, thread_id: 44, series_title: 'Uncanny X-Men', issue_number: null })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    expect(screen.getByLabelText('Current thread of series')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add thread' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Whole comic series')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add series' })).not.toBeInTheDocument()

    selectThread('Current thread of series', 'uncanny', 'Uncanny X-Men')
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Uncanny X-Men added to crossover as 1 thread member.')
  })

  it('shows no unfiltered dump on empty series search and requires typing', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    expect(screen.getAllByText('Type to search comics')).toHaveLength(2)
    expect(screen.queryByRole('listbox', { name: 'Current thread of series results' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Current thread of series'), { target: { value: 'Nova' } })
    expect(await screen.findByRole('listbox', { name: 'Current thread of series results' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Nova/ })).toBeInTheDocument()
  })

  it('distinguishes ambiguous series with counts in dropdown', async () => {
    const starman = { ...thread, id: 99, title: 'Starman', format: 'single issues', issues_remaining: 61, total_issues: 80 }
    const starmanV2 = { ...thread, id: 100, title: 'Starman (Vol. 2) (1994 - 2001)', format: 'single issues', issues_remaining: 5, total_issues: 10 }
    threadApi.list.mockResolvedValue({ threads: [starman, starmanV2], next_page_token: null })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.change(screen.getByLabelText('Current thread of series'), { target: { value: 'Starman' } })
    const options = await screen.findAllByRole('option')
    const texts = options.map((o) => o.textContent ?? '')
    expect(texts.some((t) => t.includes('61 remaining'))).toBe(true)
    expect(texts.some((t) => t.includes('5 remaining'))).toBe(true)
  })
})
