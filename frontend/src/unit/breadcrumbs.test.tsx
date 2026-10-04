import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import Breadcrumbs from '../components/Breadcrumbs'
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

function breadcrumbScript(): HTMLScriptElement | null {
  return document.head.querySelector<HTMLScriptElement>(
    `script#${BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID}`,
  )
}

function visibleBreadcrumbLabels(): string[] {
  const nav = screen.getByRole('navigation', { name: 'Breadcrumb' })
  return Array.from(nav.querySelectorAll('li')).map(li => li.textContent ?? '')
}

beforeEach(() => {
  cleanup()
  removeStructuredDataScript(BREADCRUMB_STRUCTURED_DATA_SCRIPT_ID)
})

test('breadcrumb UI and BreadcrumbList schema agree', () => {
  render(
    <MemoryRouter initialEntries={['/thread/42']}>
      <Breadcrumbs items={[{ label: 'Queue', to: '/queue' }, { label: 'Saga' }]} />
    </MemoryRouter>,
  )

  const nav = screen.getByRole('navigation', { name: 'Breadcrumb' })
  const links = Array.from(nav.querySelectorAll('a'))
  expect(links).toHaveLength(1)
  expect(links[0]?.textContent).toBe('Queue')
  expect(links[0]?.getAttribute('href')).toBe('/queue')

  const current = nav.querySelector('[aria-current="page"]')
  expect(current?.textContent).toBe('Saga')

  const script = breadcrumbScript()
  expect(script).not.toBeNull()
  expect(script?.type).toBe('application/ld+json')
  // SAFETY: script.textContent is valid JSON from the scaffolded BreadcrumbList structure
  const schema = JSON.parse(script?.textContent ?? '') as BreadcrumbList
  expect(schema['@context']).toBe('https://schema.org')
  expect(schema['@type']).toBe('BreadcrumbList')
  expect(schema.itemListElement).toEqual([
    { '@type': 'ListItem', position: 1, name: 'Queue', item: `${window.location.origin}/queue` },
    { '@type': 'ListItem', position: 2, name: 'Saga' },
  ])

  // The visible trail and the schema describe the same pages in the same order.
  const schemaNames = schema.itemListElement.map(node => node.name)
  expect(visibleBreadcrumbLabels()).toEqual(['Queue', 'Saga'])
  expect(schemaNames).toEqual(['Queue', 'Saga'])
})

test('unmounting the breadcrumb trail removes its schema', () => {
  const view = render(
    <MemoryRouter>
      <Breadcrumbs items={[{ label: 'History', to: '/history' }, { label: 'Session #7' }]} />
    </MemoryRouter>,
  )
  expect(breadcrumbScript()).not.toBeNull()

  view.unmount()
  expect(breadcrumbScript()).toBeNull()
})

test('re-rendering with new items updates the schema in place', () => {
  const view = render(
    <MemoryRouter>
      <Breadcrumbs items={[{ label: 'Queue', to: '/queue' }, { label: 'Saga' }]} />
    </MemoryRouter>,
  )
  const firstScript = breadcrumbScript()

  view.rerender(
    <MemoryRouter>
      <Breadcrumbs items={[{ label: 'Queue', to: '/queue' }, { label: 'Monstress' }]} />
    </MemoryRouter>,
  )

  const secondScript = breadcrumbScript()
  expect(secondScript).toBe(firstScript)
  const schema = JSON.parse(secondScript?.textContent ?? '') as BreadcrumbList
  expect(schema.itemListElement.map(node => node.name)).toEqual(['Queue', 'Monstress'])
})

test('thread detail breadcrumbs match the visible trail', async () => {
  const routeParams = { id: '42' }
  vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
    return {
      ...actual,
      useNavigate: () => vi.fn(),
      useParams: () => routeParams,
      useLocation: () => ({ state: undefined }),
    }
  })
  vi.mock('../hooks/useThread', async () => {
    const actual = await vi.importActual<typeof import('../hooks/useThread')>('../hooks/useThread')
    return { ...actual, useUpdateThread: vi.fn() }
  })
  vi.mock('../services/api-threads', () => ({
    threadsApi: { get: vi.fn().mockResolvedValue({ id: 42, title: 'Saga', format: 'Comics' }) },
  }))
  vi.mock('../services/api', () => ({
    dependenciesApi: {
      getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }))
  vi.mock('../services/api-issues', () => ({ issuesApi: { list: vi.fn() } }))

  const { default: ThreadDetailView } = await import('../pages/ThreadDetailView')
  const { ToastProvider } = await import('../contexts/ToastProvider')

  render(
    <ToastProvider>
      <ThreadDetailView />
    </ToastProvider>,
  )

  expect(await screen.findByRole('navigation', { name: 'Breadcrumb' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Queue' })).toHaveAttribute('href', '/queue')

  const schema = JSON.parse(breadcrumbScript()?.textContent ?? '') as BreadcrumbList
  expect(schema.itemListElement.map(node => node.name)).toEqual(['Queue', 'Saga'])
  expect(visibleBreadcrumbLabels()).toEqual(['Queue', 'Saga'])
})
