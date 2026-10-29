import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueRatingUndoNotice } from '../pages/thread-detail/IssueRatingUndoNotice'
import { useUndo } from '../hooks/useUndo'
import { invalidateAfterUndo } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'

vi.mock('../hooks/useUndo', () => ({
  useUndo: vi.fn(),
}))

vi.mock('../query/cacheEffects', () => ({
  invalidateAfterUndo: vi.fn(),
}))

describe('IssueRatingUndoNotice', () => {
  const mutate = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mutate.mockResolvedValue(undefined)
    vi.mocked(useUndo).mockReturnValue({
      mutate,
      isPending: false,
      isError: false,
    })
    vi.mocked(invalidateAfterUndo).mockResolvedValue()
  })

  it('undoes the exact snapshot returned by the row rating', async () => {
    const onUndone = vi.fn()

    render(
      <IssueRatingUndoNotice
        threadId={7}
        issueNumber="2"
        rating={4}
        sessionId={21}
        snapshotId={31}
        onUndone={onUndone}
      />,
    )

    expect(screen.getByText('Rated issue #2 4/5.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))

    await waitFor(() => expect(onUndone).toHaveBeenCalledTimes(1))
    expect(mutate).toHaveBeenCalledWith({ sessionId: 21, snapshotId: 31 })
    expect(invalidateAfterUndo).toHaveBeenCalledWith(queryClient, 7)
  })

  it('keeps the notice and reports a failed undo', async () => {
    mutate.mockRejectedValueOnce(new Error('conflict'))
    const onUndone = vi.fn()

    render(
      <IssueRatingUndoNotice
        threadId={7}
        issueNumber="2"
        rating={4}
        sessionId={21}
        snapshotId={31}
        onUndone={onUndone}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to undo rating')
    expect(onUndone).not.toHaveBeenCalled()
  })
})
