import { render, screen, waitFor } from '@testing-library/react'
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

describe('Action Sheet Snooze/Unsnooze', () => {
  const mockSnoozeMutation = { mutate: vi.fn(), isPending: false }
  const mockUnsnoozeMutation = { mutate: vi.fn(), isPending: false }

  beforeEach(() => {
    mockSnoozeMutation.mutate.mockReset()
    mockUnsnoozeMutation.mutate.mockReset()
    useSnooze.mockReturnValue(mockSnoozeMutation)
    useUnsnooze.mockReturnValue(mockUnsnoozeMutation)
  })

  it('opens action sheet when clicking thread card', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <QueuePage />
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    expect(threadCard).toBeInTheDocument()

    await user.click(threadCard)
    expect(screen.getByText('Read Now')).toBeInTheDocument()
    expect(screen.getByText('Move to Front')).toBeInTheDocument()
    expect(screen.getByText('Move to Back')).toBeInTheDocument()
    expect(screen.getByText('Snooze')).toBeInTheDocument()
    expect(screen.getByText('Edit Thread')).toBeInTheDocument()
  })

  it('calls snooze mutation when thread is not snoozed and snooze action is clicked', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <QueuePage />
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    await user.click(threadCard)

    const snoozeButton = screen.getByText('Snooze')
    await user.click(snoozeButton)

    expect(mockSnoozeMutation.mutate).toHaveBeenCalled()
    expect(mockUnsnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('calls unsnooze mutation when thread is snoozed and unsnooze action is clicked', async () => {
    useSession.mockReturnValue({
      data: {
        snoozed_threads: [{ id: 1, title: 'Saga', format: 'Comic' }]
      },
      refetch: vi.fn(),
    })

    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <QueuePage />
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    await user.click(threadCard)

    const unsnoozeButton = screen.getByText('Unsnooze')
    await user.click(unsnoozeButton)

    expect(mockUnsnoozeMutation.mutate).toHaveBeenCalledWith(1)
    expect(mockSnoozeMutation.mutate).not.toHaveBeenCalled()
  })

  it('refetches session and threads after snooze action', async () => {
    const mockRefetchSession = vi.fn()
    const mockRefetch = vi.fn()
    useSession.mockReturnValue({
      data: { snoozed_threads: [] },
      refetch: mockRefetchSession,
    })
    useThreads.mockReturnValue({
      data: [
        { id: 1, title: 'Saga', format: 'Comic', status: 'active', queue_position: 1, issues_remaining: 5 },
      ],
      isLoading: false,
      refetch: mockRefetch,
    })

    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <QueuePage />
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    await user.click(threadCard)

    const snoozeButton = screen.getByText('Snooze')
    await user.click(snoozeButton)

    await waitFor(() => {
      expect(mockRefetchSession).toHaveBeenCalled()
      expect(mockRefetch).toHaveBeenCalled()
    })
  })
})

describe('Keyboard Accessibility', () => {
  it('opens action sheet when pressing Enter on thread card', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <QueuePage />
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    threadCard.focus()
    await user.keyboard('{Enter}')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })

  it('opens action sheet when pressing Space on thread card', async () => {
    const user = userEvent.setup()
    render(
      <BrowserRouter>
        <QueuePage />
      </BrowserRouter>
    )

    const threadCard = screen.getByText('Saga').closest('[role="button"]') as HTMLElement
    threadCard.focus()
    await user.keyboard(' ')

    expect(screen.getByText('Read Now')).toBeInTheDocument()
  })
})
