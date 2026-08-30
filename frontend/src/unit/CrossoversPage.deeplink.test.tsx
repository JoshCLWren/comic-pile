import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { dependencyGroupsApi } from '../services/api-dependency-groups'

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

const api = vi.mocked(dependencyGroupsApi)

const annihilation = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [
    { id: 1, issue_id: 11, thread_id: null, position: 1, series_title: 'Nova', issue_number: '11' },
    { id: 2, issue_id: null, thread_id: 22, position: 2, series_title: 'Nova', issue_number: null },
  ],
}

const secretWars = {
  id: 8,
  name: 'Secret Wars',
  created_at: '2026-08-07T00:00:00Z',
  memberships: [],
}

function renderPage(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <CrossoversPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue([annihilation, secretWars])
})

describe('CrossoversPage deep links (issue #1877)', () => {
  it('expands exactly the crossover named by ?group= without user interaction', async () => {
    renderPage('/crossovers?group=8')

    const secretWarsButton = await screen.findByRole('button', { name: /Secret Wars.*0 members/ })
    expect(await screen.findByText('This crossover has no comics yet.')).toBeVisible()
    expect(secretWarsButton).toHaveAttribute('aria-expanded', 'true')

    const annihilationButton = screen.getByRole('button', { name: /Annihilation.*2 members/ })
    expect(annihilationButton).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Nova #11')).not.toBeInTheDocument()
  })

  it('retains carried starts-at context inside the deep-linked crossover detail', async () => {
    renderPage('/crossovers?group=7&starts_at=14')

    const annihilationButton = await screen.findByRole('button', { name: /Annihilation.*2 members/ })
    expect(await screen.findByText('Starts at #14')).toBeVisible()
    expect(screen.getByText('Nova #11')).toBeVisible()
    expect(annihilationButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /Secret Wars.*0 members/ })).toHaveAttribute('aria-expanded', 'false')
  })

  it('omits starts-at context when the deep link does not carry it', async () => {
    renderPage('/crossovers?group=7')

    expect(await screen.findByText('Nova #11')).toBeVisible()
    expect(screen.queryByText('Starts at #14')).not.toBeInTheDocument()
  })

  it('ignores unknown crossover ids instead of expanding a wrong group', async () => {
    renderPage('/crossovers?group=99')

    await screen.findByRole('button', { name: /Annihilation.*2 members/ })
    expect(screen.getByRole('button', { name: /Annihilation.*2 members/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: /Secret Wars.*0 members/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Starts at #14')).not.toBeInTheDocument()
  })

  it('keeps manual toggling working after a deep-linked expansion', async () => {
    renderPage('/crossovers?group=7&starts_at=14')

    const annihilationButton = await screen.findByRole('button', { name: /Annihilation.*2 members/ })
    await waitFor(() => expect(annihilationButton).toHaveAttribute('aria-expanded', 'true'))

    fireEvent.click(annihilationButton)
    expect(annihilationButton).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Starts at #14')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Secret Wars.*0 members/ }))
    expect(screen.getByRole('button', { name: /Secret Wars.*0 members/ })).toHaveAttribute('aria-expanded', 'true')
  })
})
