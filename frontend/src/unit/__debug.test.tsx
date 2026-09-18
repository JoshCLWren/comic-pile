import { fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(), get: vi.fn(), create: vi.fn(), rename: vi.fn(), delete: vi.fn(),
    addMember: vi.fn(), addIssueRange: vi.fn(), removeMember: vi.fn(),
    listForThread: vi.fn(), listForThreads: vi.fn(), plansForGroup: vi.fn(), getDetail: vi.fn(),
  },
}))
vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  threadsApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(), reactivate: vi.fn(), listStale: vi.fn(), setPending: vi.fn(), setCurrentIssue: vi.fn(), listCompleted: vi.fn() },
}))
vi.mock('../services/api-issues', () => ({
  issuesApi: { list: vi.fn() },
}))

const api = vi.mocked(dependencyGroupsApi)
const threadApi = vi.mocked(threadsApi)

const crossover = { id: 7, name: 'Annihilation', created_at: '2026-08-06T00:00:00Z', memberships: [ { id: 1, issue_id: 31, thread_id: null, series_title: 'Nova', issue_number: '2' }, { id: 2, issue_id: null, thread_id: 22, series_title: 'Nova', issue_number: null } ] }
const thread = { id: 22, title: 'Nova', format: 'single issues', issues_remaining: 3, total_issues: 3, queue_position: 4, status: 'active', is_blocked: false, blocking_reasons: [], created_at: '2026-08-01T00:00:00Z' }
const xmenThread = { ...thread, id: 44, title: 'Uncanny X-Men', queue_position: 8 }

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function renderPage() {
  return render(<MemoryRouter><CrossoversPage /></MemoryRouter>, { wrapper: createWrapper() })
}

beforeEach(() => {
  vi.spyOn(dependencyGroupsApi, 'list').mockResolvedValue([crossover])
  vi.spyOn(dependencyGroupsApi, 'get').mockResolvedValue(crossover)
  vi.spyOn(dependencyGroupsApi, 'create').mockResolvedValue({ id: 0, name: '', created_at: '', memberships: [] })
  vi.spyOn(dependencyGroupsApi, 'rename').mockResolvedValue({ id: 0, name: '', created_at: '', memberships: [] })
  vi.spyOn(dependencyGroupsApi, 'delete').mockResolvedValue(undefined)
  vi.spyOn(dependencyGroupsApi, 'addMember').mockResolvedValue({ id: 0, issue_id: null, thread_id: null })
  vi.spyOn(dependencyGroupsApi, 'addIssueRange').mockResolvedValue({ thread_id: 0, start_position: 0, end_position: 0, added_issue_ids: [], already_present_issue_ids: [] })
  vi.spyOn(dependencyGroupsApi, 'removeMember').mockResolvedValue(undefined)
  vi.spyOn(threadsApi, 'list').mockResolvedValue({ threads: [thread, xmenThread], next_page_token: null })
  vi.spyOn(threadsApi, 'get').mockResolvedValue(thread)
})
afterEach(() => { vi.restoreAllMocks() })

describe('debug', () => {
  it('debug selector', async () => {
    api.addMember.mockResolvedValue({ id: 3, issue_id: null, thread_id: 44, series_title: 'Uncanny X-Men', issue_number: null })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))
    const input = screen.getByLabelText('Current thread of series')
    console.log('Initial input value:', JSON.stringify(input.value))
    fireEvent.change(input, { target: { value: 'uncanny' } })
    console.log('After change input value:', JSON.stringify(input.value))
    const listbox = await screen.findByRole('listbox', { name: 'Current thread of series results' })
    const option = within(listbox).getByRole('option', { name: /Uncanny X-Men/ })
    console.log('Option type:', option.getAttribute('type'))
    fireEvent.click(option)
    console.log('After click input value:', JSON.stringify(input.value))
    try {
      await waitFor(() => expect(input).toHaveValue('Uncanny X-Men'), { timeout: 2000 })
      console.log('WaitFor succeeded')
    } catch {
      console.log('WAITFOR FAILED')
    }
  })
})
