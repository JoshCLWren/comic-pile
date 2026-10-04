import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { useUpdateThread } from '../hooks/useThread'
import {
  BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID,
  removeStructuredDataScript,
} from '../seo/structuredData'

interface ListItemNode {
  '@type': string
  position: number
  name: string
  item?: string
}

interface BreadcrumbList {
  '@context': string
  '@type': string
  itemListElement: ListItemNode[]
}

const routeParams = { id: '42' }

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => routeParams }
})
vi.mock('../hooks/useThread', async () => {
  const actual = await vi.importActual<typeof import('../hooks/useThread')>('../hooks/useThread')
  return { ...actual, useUpdateThread: vi.fn() }
})
vi.mock('../services/api-threads', () => ({ threadsApi: { get: vi.fn() } }))
vi.mock('../services/api-dependencies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-dependencies')>()
  return {
    ...actual,
    dependenciesApi: {
      getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }
})
vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn() } }))

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)

beforeEach(() => {
  removeStructuredDataScript(BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID)
  // SAFETY: the hook mock returns only the fields the view reads
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  // SAFETY: the stubbed thread supplies only the fields this view reads
  mockedThreadsApiGet.mockResolvedValue({
    id: 42,
    title: 'Saga',
    format: 'Comics',
    issues_remaining: 5,
    queue_position: 1,
    status: 'active',
    total_issues: null,
    notes: null,
  } as never)
  mockedIssuesApiList.mockResolvedValue({
    issues: [],
    next_page_token: null,
    total_count: 0,
    page_size: 100,
  } as never)
  // SAFETY: the component under test only reads the fields the stub exposes
  vi.mocked(dependenciesApi.getConnectedThreads).mockResolvedValue({
    thread_id: 42,
    connected_threads: [],
  } as never)
})

function breadcrumbScript(): HTMLScriptElement | null {
  return document.head.querySelector<HTMLScriptElement>(
    `script#${BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID}`,
  )
}

function renderThreadDetail() {
  return render(
    <MemoryRouter initialEntries={['/thread/42']}>
      <ToastProvider>
        <Routes>
          <Route path="/thread/:id" element={<ThreadDetailView />} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  )
}

it('thread detail breadcrumbs match the visible trail', async () => {
  renderThreadDetail()

  const nav = await screen.findByRole('navigation', { name: 'Breadcrumb' })
  expect(screen.getByRole('link', { name: 'Queue' })).toHaveAttribute('href', '/queue')
  expect(nav.querySelector('[aria-current="page"]')?.textContent).toBe('Thread')

  const schema = JSON.parse(breadcrumbScript()?.textContent ?? '') as BreadcrumbList
  expect(schema['@context']).toBe('https://schema.org')
  expect(schema['@type']).toBe('BreadcrumbList')
  expect(schema.itemListElement).toEqual([
    {
      '@type': 'ListItem',
      position: 1,
      name: 'Queue',
      item: `${window.location.origin}/queue`,
    },
    { '@type': 'ListItem', position: 2, name: 'Thread' },
  ])

  const visibleLabels = Array.from(nav.querySelectorAll('li')).map(
    li => li.querySelector('a, [aria-current="page"]')?.textContent ?? '',
  )
  expect(visibleLabels).toEqual(['Queue', 'Thread'])
  expect(schema.itemListElement.map(node => node.name)).toEqual(visibleLabels)
})