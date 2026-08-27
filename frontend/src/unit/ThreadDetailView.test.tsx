import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { useUpdateThread } from '../hooks/useThread'
import { dependenciesApi, threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import { renderWithClient } from './queryTestWrapper'

const navigateSpy = vi.fn()
const routeParams = { id: '1' }
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy, useParams: () => routeParams }
})
vi.mock('../hooks/useThread', () => ({ useUpdateThread: vi.fn() }))
vi.mock('../services/api', () => ({
  threadsApi: { get: vi.fn() },
  dependenciesApi: {
    getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
    getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
  },
}))
vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn() } }))

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mockedConnectedThreads = vi.mocked(dependenciesApi.getConnectedThreads)

beforeEach(() => {
  routeParams.id = '1'
  navigateSpy.mockReset()
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5, queue_position: 1,
    status: 'active', total_issues: null, notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValue({ issues: [], next_page_token: null, total_count: 0, page_size: 100 })
})

function renderPage() {
  return renderWithClient(
    <ToastProvider><ThreadDetailView /></ToastProvider>,
    { innerWrapper: ({ children }) => children }
  )
}