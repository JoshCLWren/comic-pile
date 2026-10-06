import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PostRateCopyPrompt, type PostRateReference } from '../pages/RollPage/components/PostRateCopyPrompt'
import { useUndoLatestRating } from '../hooks/useUndo'

vi.mock('../hooks/useUndo', () => ({
  useUndoLatestRating: vi.fn(),
}))

const mockedUseUndoLatestRating = vi.mocked(useUndoLatestRating)
const undoLatest = vi.fn()

const reference: PostRateReference = {
  title: 'B.P.R.D.: War on Frogs',
  issueNumber: '4',
  rating: 4,
}

function renderPrompt(
  overrides?: {
    reference?: PostRateReference | null
    onDismiss?: () => void
    sessionId?: number | null
    onUndone?: () => void
  },
) {
  const props = {
    reference,
    onDismiss: vi.fn(),
    ...overrides,
  }
  render(<PostRateCopyPrompt {...props} />)
  return props
}

beforeEach(() => {
  undoLatest.mockReset().mockResolvedValue(true)
  mockedUseUndoLatestRating.mockReturnValue({ undoLatest, isPending: false })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('PostRateCopyPrompt', () => {
  it('renders nothing when no reference is provided', () => {
    renderPrompt({ reference: null })
    expect(screen.queryByTestId('post-rate-copy-prompt')).not.toBeInTheDocument()
  })

  it('names the rated comic and score to confirm what will be copied', () => {
    renderPrompt()
    expect(screen.getByTestId('post-rate-copy-prompt')).toHaveTextContent(
      'You just rated B.P.R.D.: War on Frogs 4 a 4/5.',
    )
    expect(screen.getByText('Copies “B.P.R.D.: War on Frogs 4”')).toBeInTheDocument()
  })

  it('copies the same title + issue string the pre-rate control uses', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    renderPrompt()
    await user.click(
      screen.getByRole('button', { name: 'Copy B.P.R.D.: War on Frogs 4' }),
    )

    expect(writeText).toHaveBeenCalledWith('B.P.R.D.: War on Frogs 4')
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })

  it('keeps the issue number with its own formatting when copying', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    renderPrompt({ reference: { title: 'Cable', issueNumber: '#62', rating: 5 } })
    await user.click(screen.getByRole('button', { name: 'Copy Cable #62' }))

    expect(writeText).toHaveBeenCalledWith('Cable #62')
  })

  it('shows a retry path when clipboard writing fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('clipboard denied'))

    renderPrompt()
    await user.click(
      screen.getByRole('button', { name: 'Copy B.P.R.D.: War on Frogs 4' }),
    )

    expect(screen.getByRole('button', { name: 'Copy B.P.R.D.: War on Frogs 4' })).toHaveTextContent(
      'Retry copy',
    )
    expect(screen.getByText(/Copy failed/)).toBeInTheDocument()
    expect(screen.getByText(/Copy failed/).getAttribute('role')).toBe('status')

    vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValueOnce(undefined)
    await user.click(
      screen.getByRole('button', { name: 'Copy B.P.R.D.: War on Frogs 4' }),
    )
    expect(screen.getByText('Copied')).toBeInTheDocument()
  })

  it('dismisses on the Dismiss action and is keyboard accessible', async () => {
    const user = userEvent.setup()
    const props = renderPrompt()

    const dismissButton = screen.getByRole('button', { name: 'Dismiss rating saved notice' })
    dismissButton.focus()
    expect(document.activeElement).toBe(dismissButton)

    await user.click(dismissButton)
    expect(props.onDismiss).toHaveBeenCalledTimes(1)
  })

  it('offers an Undo action directly on the just-rated notice', async () => {
    const user = userEvent.setup()
    const onUndone = vi.fn()
    renderPrompt({ sessionId: 12, onUndone })

    await user.click(screen.getByRole('button', { name: 'Undo rating of B.P.R.D.: War on Frogs 4' }))

    expect(undoLatest).toHaveBeenCalledWith(12)
    expect(onUndone).toHaveBeenCalledTimes(1)
  })

  it('hides the Undo action when no session is available', () => {
    renderPrompt({ sessionId: null })
    expect(screen.queryByRole('button', { name: /undo rating/i })).not.toBeInTheDocument()
  })

  it('keeps the notice when the undo finds nothing to revert', async () => {
    const user = userEvent.setup()
    undoLatest.mockResolvedValueOnce(false)
    const onUndone = vi.fn()
    renderPrompt({ sessionId: 12, onUndone })

    await user.click(screen.getByRole('button', { name: 'Undo rating of B.P.R.D.: War on Frogs 4' }))

    expect(undoLatest).toHaveBeenCalledWith(12)
    expect(onUndone).not.toHaveBeenCalled()
    expect(screen.getByTestId('post-rate-copy-prompt')).toBeInTheDocument()
  })
})
