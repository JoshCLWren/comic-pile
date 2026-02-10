import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useThreads,
  useUpdateThread,
} from '../hooks/useThread'
import { useMoveToBack, useMoveToFront, useMoveToPosition } from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'

vi.mock('../hooks/useThread', () => ({
  useThreads: vi.fn(),
  useCreateThread: vi.fn(),
  useUpdateThread: vi.fn(),
  useDeleteThread: vi.fn(),
  useReactivateThread: vi.fn(),
}))

vi.mock('../hooks/useQueue', () => ({
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useMoveToPosition: vi.fn(),
}))

vi.mock('../hooks/useSession', () => ({
  useSession: vi.fn(),
}))

vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))

beforeEach(() => {
  useThreads.mockReturnValue({
    data: [
      { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
      { id: 2, title: 'Descender', format: 'Comic', status: 'completed', issues_remaining: 0 },
    ],
    isLoading: false,
    refetch: vi.fn(),
  })
  useCreateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useUpdateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useDeleteThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useReactivateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useMoveToPosition.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useSession.mockReturnValue({
    data: { snoozed_threads: [] },
    refetch: vi.fn(),
  })
  useUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  useSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
})

it('renders queue items and opens create modal', async () => {
  const user = userEvent.setup()
  render(
    <BrowserRouter>
      <QueuePage />
    </BrowserRouter>
  )

  expect(screen.getByText('Saga')).toBeInTheDocument()
  expect(screen.getByText('Descender')).toBeInTheDocument()
  expect(screen.getByText('#1')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /add thread/i }))
  expect(screen.getByRole('heading', { name: /create thread/i })).toBeInTheDocument()
})
