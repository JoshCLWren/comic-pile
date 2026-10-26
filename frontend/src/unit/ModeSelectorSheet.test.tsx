import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import ModeSelectorSheet from '../components/ModeSelectorSheet'
import type { SessionModeState } from '../types/rollBootstrap'

const defaultProps = {
  isOpen: true,
  // SAFETY: the sheet starts with no active session mode
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

  it('moves and selects with ArrowRight/ArrowDown inside the bandwidth group', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'balanced', intent: 'momentum' })}
        onSubmit={onSubmit}
      />,
    )

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    const balanced = within(bandwidthGroup).getByRole('radio', { name: /Balanced/ })
    balanced.focus()

    await user.keyboard('{ArrowRight}')
    expect(onSubmit).toHaveBeenLastCalledWith({ bandwidth: 'deep', intent: 'momentum' })

    within(bandwidthGroup).getByRole('radio', { name: /Deep/ }).focus()
    await user.keyboard('{ArrowDown}')
    expect(onSubmit).toHaveBeenLastCalledWith({ bandwidth: 'light', intent: 'momentum' })
  })

  it('wraps arrow navigation at both ends of a group', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'light', intent: 'familiar' })}
        onSubmit={onSubmit}
      />,
    )

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    within(bandwidthGroup).getByRole('radio', { name: /Light/ }).focus()
    await user.keyboard('{ArrowLeft}')
    expect(onSubmit).toHaveBeenLastCalledWith({ bandwidth: 'deep', intent: 'familiar' })

    within(bandwidthGroup).getByRole('radio', { name: /Deep/ }).focus()
    await user.keyboard('{ArrowUp}')
    expect(onSubmit).toHaveBeenLastCalledWith({ bandwidth: 'balanced', intent: 'familiar' })
  })

  it('jumps to the group edges with Home and End', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'light', intent: 'explore' })}
        onSubmit={onSubmit}
      />,
    )

    const intentGroup = screen.getByRole('radiogroup', { name: 'Intent' })
    within(intentGroup).getByRole('radio', { name: /Explore/ }).focus()

    await user.keyboard('{Home}')
    expect(onSubmit).toHaveBeenLastCalledWith({ bandwidth: 'light', intent: 'balanced' })

    within(intentGroup).getByRole('radio', { name: /Balanced/ }).focus()
    await user.keyboard('{End}')
    expect(onSubmit).toHaveBeenLastCalledWith({ bandwidth: 'light', intent: 'random' })
  })

  it('keeps arrow navigation inside the focused group', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'deep', intent: 'momentum' })}
        onSubmit={onSubmit}
      />,
    )

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    within(bandwidthGroup).getByRole('radio', { name: /Deep/ }).focus()
    await user.keyboard('{ArrowRight}')

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenLastCalledWith({ bandwidth: 'light', intent: 'momentum' })
  })

  it('moves the checked selection and focus with arrow keys', async () => {
    const user = userEvent.setup()

    function StatefulSheet() {
      const [current, setCurrent] = useState<SessionModeState>({
        bandwidth: 'balanced',
        intent: 'balanced',
      })
      return (
        <ModeSelectorSheet
          isOpen
          currentMode={current}
          onClose={() => undefined}
          onSubmit={async (patch) => {
            setCurrent((previous) => ({ ...previous, ...patch }))
          }}
        />
      )
    }

    render(<StatefulSheet />)

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    const balanced = within(bandwidthGroup).getByRole('radio', { name: /Balanced/ })
    balanced.focus()
    await user.keyboard('{ArrowDown}')

    const deep = within(bandwidthGroup).getByRole('radio', { name: /Deep/ })
    expect(deep).toHaveAttribute('aria-checked', 'true')
    expect(balanced).toHaveAttribute('aria-checked', 'false')
    expect(deep).toHaveFocus()
  })

  it('ignores non-navigation keys in a radio group', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(<ModeSelectorSheet {...defaultProps} onSubmit={onSubmit} />)

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    const balanced = within(bandwidthGroup).getByRole('radio', { name: /Balanced/ })
    balanced.focus()
    fireEvent.keyDown(balanced, { key: 'Tab' })
    fireEvent.keyDown(balanced, { key: 'a' })

    expect(onSubmit).not.toHaveBeenCalled()
    expect(balanced).toHaveFocus()
  })

  it('moves focus to the error and keeps the sheet open when an arrow-selected mode fails', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockRejectedValue(new Error('API error'))

    render(
      <ModeSelectorSheet
        {...defaultProps}
        currentMode={mode({ bandwidth: 'balanced', intent: 'balanced' })}
        onSubmit={onSubmit}
      />,
    )

    const bandwidthGroup = screen.getByRole('radiogroup', { name: 'Bandwidth' })
    within(bandwidthGroup).getByRole('radio', { name: /Balanced/ }).focus()
    await user.keyboard('{ArrowRight}')

    expect(onSubmit).toHaveBeenCalledWith({ bandwidth: 'deep', intent: 'balanced' })
    const error = await screen.findByTestId('mode-selector-error')
    expect(error).toHaveFocus()
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


it('announces saving while preserving radio names and preventing overlapping writes', async () => {
  const user = userEvent.setup()
  let complete: (() => void) | undefined
  const onSubmit = vi.fn(() => new Promise<void>((resolve) => { complete = resolve }))
  const onClose = vi.fn()
  render(<ModeSelectorSheet {...defaultProps} onSubmit={onSubmit} onClose={onClose} />)
  await user.click(within(screen.getByRole('radiogroup', { name: 'Bandwidth' })).getByRole('radio', { name: /Deep/ }))
  expect(screen.getByRole('status')).toHaveTextContent('Saving…')
  for (const radio of screen.getAllByRole('radio')) expect(radio).toHaveAccessibleName()
  await user.click(within(screen.getByRole('radiogroup', { name: 'Intent' })).getByRole('radio', { name: /Random/ }))
  expect(onSubmit).toHaveBeenCalledTimes(1)
  expect(onClose).not.toHaveBeenCalled()
  await act(async () => { complete?.() })
  expect(onClose).toHaveBeenCalledTimes(1)
  expect(screen.queryByTestId('mode-selector-saving')).not.toBeInTheDocument()
})

it('retries the failed selection without claiming an unconfirmed mode was saved', async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(undefined)
  const onClose = vi.fn()
  render(<ModeSelectorSheet {...defaultProps} onSubmit={onSubmit} onClose={onClose} />)
  await user.click(within(screen.getByRole('radiogroup', { name: 'Intent' })).getByRole('radio', { name: /Random/ }))
  expect(await screen.findByRole('alert')).toHaveFocus()
  expect(onClose).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Retry' }))
  expect(onSubmit).toHaveBeenNthCalledWith(2, { bandwidth: 'balanced', intent: 'random' })
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('does not let an old save close a reopened dialog', async () => {
  const user = userEvent.setup()
  let complete: (() => void) | undefined
  const onSubmit = vi.fn(() => new Promise<void>((resolve) => { complete = resolve }))
  const onClose = vi.fn()
  const props = { ...defaultProps, onSubmit, onClose }
  const view = render(<ModeSelectorSheet {...props} />)
  await user.click(within(screen.getByRole('radiogroup', { name: 'Bandwidth' })).getByRole('radio', { name: /Deep/ }))
  view.rerender(<ModeSelectorSheet {...props} isOpen={false} />)
  view.rerender(<ModeSelectorSheet {...props} isOpen />)
  await act(async () => { complete?.() })
  expect(onClose).not.toHaveBeenCalled()
  expect(screen.getByTestId('mode-selector-sheet')).toBeVisible()
})
