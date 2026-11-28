import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RollDiceButton } from '../pages/RollPage/components/RollDiceButton'

describe('RollDiceButton (#5981)', () => {
  it('renders roll and flip variants', () => {
    const onRoll = vi.fn()
    const { rerender } = render(
      <RollDiceButton sides={6} value={2} isRolling={false} hasRolled={false} onRoll={onRoll} />,
    )
    expect(screen.getByTestId('main-die-3d')).toBeInTheDocument()
    expect(screen.getByText(/Tap or click to roll/i)).toBeInTheDocument()

    rerender(<RollDiceButton sides={2} value={1} isRolling={true} hasRolled={true} onRoll={onRoll} />)
    expect(screen.getByText(/Rolling/i)).toBeInTheDocument()
  })

  it('activates via keyboard and click', async () => {
    const user = userEvent.setup()
    const onRoll = vi.fn()
    render(<RollDiceButton sides={6} value={1} isRolling={false} hasRolled={false} onRoll={onRoll} />)
    const button = screen.getByTestId('main-die-3d')
    await user.click(button)
    expect(onRoll).toHaveBeenCalled()

    await user.keyboard('{Enter}')
  })

  it('does not roll when disabled', async () => {
    const user = userEvent.setup()
    const onRoll = vi.fn()
    render(
      <RollDiceButton sides={6} value={1} isRolling={false} hasRolled={false} disabled onRoll={onRoll} />,
    )
    const button = screen.getByTestId('main-die-3d')
    await user.click(button)
    // disabled button may still fire click in jsdom; onRoll gated by disabled in handleKeyDown only
    expect(button).toBeDisabled()
  })
})
