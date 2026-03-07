import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import HistoryPage from '../pages/HistoryPage'
import { useSessions } from '../hooks/useSession'

vi.mock('../hooks/useSession', () => ({ useSessions: vi.fn() }))

const mockedUseSessions = vi.mocked(useSessions) as any

beforeEach(() => {
  mockedUseSessions.mockReturnValue({ data: [], isLoading: false })
})

it('renders empty history state', () => {
  render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>
  )

  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('No sessions yet')).toBeInTheDocument()
})
