import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ModeSelectorSheet from '../components/ModeSelectorSheet'
import type { SessionModeState } from '../types/rollBootstrap'

const defaultProps = {
  isOpen: true,
  currentMode: null as SessionModeState | null,
  onClose: vi.fn(),
  onSubmit: vi.fn().mockResolvedValue(undefined),
}

function mode(overrides: Partial<SessionModeState>): SessionModeState {
  return { bandwidth: 'balanced', intent: 'balanced', ...overrides }
}

describe('ModeSelectorSheet', () => {
  it('renders nothing when isOpen is false', () => {
    const { container } = render(<ModeSelectorSheet {...defaultProps} isOpen={false} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders bandwidth and intent radio groups', () => {
    render(<ModeSelectorSheet {...defaultProps} />)

    expect(screen.getByTestId('mode-selector-sheet')).toBeInTheDocument()
    expect(screen.getByText('Reading mode')).toBeInTheDocument()

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    expect(within(bandwidthGroup).getByRole('radio', { name: /Light/ })).toBeInTheDocument()
    expect(within(bandwidthGroup).getByRole('radio', { name: /Balanced/ })).toBeInTheDocument()
    expect(within(bandwidthGroup).getByRole('radio', { name: /Deep/ })).toBeInTheDocument()

    const intentGroup = screen.getByRole('radiogroup', { name: 'Intent' })
    expect(within(intentGroup).getByRole('radio', { name: /Balanced/ })).toBeInTheDocument()
    expect(within(intentGroup).getByRole('radio', { name: /Momentum/ })).toBeInTheDocument()
    expect(within(intentGroup).getByRole('radio', { name: /Familiar/ })).toBeInTheDocument()
    expect(within(intentGroup).getByRole('radio', { name: /Explore/ })).toBeInTheDocument()
    expect(within(intentGroup).getByRole('radio', { name: /Random/ })).toBeInTheDocument()
  })

  it('shows active values as selected', () => {
    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'light', intent: 'momentum' })}
      />,
    )

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    expect(within(bandwidthGroup).getByRole('radio', { name: /Light/ })).toHaveAttribute('aria-checked', 'true')
    expect(within(bandwidthGroup).getByRole('radio', { name: /Balanced/ })).toHaveAttribute('aria-checked', 'false')
    expect(within(bandwidthGroup).getByRole('radio', { name: /Deep/ })).toHaveAttribute('aria-checked', 'false')

    const intentGroup = screen.getByRole('radiogroup', { name: 'Intent' })
    expect(within(intentGroup).getByRole('radio', { name: /Momentum/ })).toHaveAttribute('aria-checked', 'true')
    expect(within(intentGroup).getByRole('radio', { name: /Balanced/ })).toHaveAttribute('aria-checked', 'false')
  })

  it('submits bandwidth-only patch when clicking a bandwidth option', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'balanced', intent: 'momentum' })}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    )

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    await user.click(within(bandwidthGroup).getByRole('radio', { name: /Deep/ }))
    expect(onSubmit).toHaveBeenCalledWith({ bandwidth: 'deep', intent: 'momentum' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('submits intent-only patch when clicking an intent option', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()

    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'light', intent: 'balanced' })}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    )

    const intentGroup = screen.getByRole('radiogroup', { name: 'Intent' })
    await user.click(within(intentGroup).getByRole('radio', { name: /Random/ }))
    expect(onSubmit).toHaveBeenCalledWith({ bandwidth: 'light', intent: 'random' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('defaults to balanced when currentMode is null', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(<ModeSelectorSheet {...defaultProps} currentMode={null} onSubmit={onSubmit} />)

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    expect(within(bandwidthGroup).getByRole('radio', { name: /Balanced/ })).toHaveAttribute('aria-checked', 'true')

    await user.click(within(bandwidthGroup).getByRole('radio', { name: /Light/ }))
    expect(onSubmit).toHaveBeenCalledWith({ bandwidth: 'light', intent: 'balanced' })
  })

  it('shows error on submit failure', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockRejectedValue(new Error('API error'))

    render(<ModeSelectorSheet {...defaultProps} onSubmit={onSubmit} />)

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    await user.click(within(bandwidthGroup).getByRole('radio', { name: /Deep/ }))
    expect(screen.getByTestId('mode-selector-error')).toHaveTextContent('Failed to update reading mode. Please try again.')
  })

  it('shows Random intent description', () => {
    render(<ModeSelectorSheet {...defaultProps} />)

    const intentGroup = screen.getByRole('radiogroup', { name: 'Intent' })
    expect(within(intentGroup).getByRole('radio', { name: /Random/ })).toHaveAttribute(
      'aria-label',
      'Random: Unweighted legacy-style selection within the current die pool',
    )
  })

  it('disables options while submitting', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockImplementation(() => new Promise(() => {}))

    render(<ModeSelectorSheet {...defaultProps} onSubmit={onSubmit} />)

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    await user.click(within(bandwidthGroup).getByRole('radio', { name: /Deep/ }))
    expect(within(bandwidthGroup).getByRole('radio', { name: /Light/ })).toBeDisabled()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()

    render(<ModeSelectorSheet {...defaultProps} onClose={onClose} />)

    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('hides the quiz entry when quizEnabled is false', () => {
    render(<ModeSelectorSheet {...defaultProps} quizEnabled={false} />)
    expect(screen.queryByTestId('mode-selector-open-quiz')).not.toBeInTheDocument()
  })

  it('opens the quiz from the manual entry point when enabled', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()
    const onOpenQuiz = vi.fn()

    render(
      <ModeSelectorSheet
        {...defaultProps}
        onSubmit={onSubmit}
        onClose={onClose}
        quizEnabled={true}
        onOpenQuiz={onOpenQuiz}
      />,
    )

    await user.click(screen.getByTestId('mode-selector-open-quiz'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onOpenQuiz).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
