import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RollHeader } from '../pages/RollPage/components/RollHeader'
import { ReadingModeControl } from '../pages/RollPage/components/ReadingModeControl'
import type { RollBootstrapResponse, SessionModeState } from '../types/rollBootstrap'
import { formatSessionMode, readingModeLabel } from '../types/rollBootstrap'

function bootstrapWithMode(mode: SessionModeState | null | undefined): RollBootstrapResponse {
  return {
    session_id: 1,
    user_id: 1,
    current_die: 6,
    manual_die: null,
    pending_thread_id: null,
    last_rolled_result: null,
    active_thread: null,
    roll_pool: [],
    snoozed_threads: [],
    snoozed_count: 0,
    blocked_count: 0,
    blocked_threads: [],
    stale_thread_count: 0,
    stale_thread: null,
    session_mode: mode,
  }
}

const headerBaseProps = {
  currentDie: 6,
  dieSize: 6,
  displayDie: 6 as const,
  snoozedThreads: [],
  pool: [],
  isRatingView: false,
  setDiePending: false,
  clearManualDiePending: false,
  onSetDie: vi.fn(),
  onClearManualDie: vi.fn(),
  onOpenOverride: vi.fn(),
  onOpenDieModal: vi.fn(),
}

describe('reading mode label helpers', () => {
  it('maps canonical bandwidth and intent values to human-readable labels', () => {
    expect(readingModeLabel('light')).toBe('Light')
    expect(readingModeLabel('BALANCED')).toBe('Balanced')
    expect(readingModeLabel('deep')).toBe('Deep')
    expect(readingModeLabel('momentum')).toBe('Momentum')
    expect(readingModeLabel('familiar')).toBe('Familiar')
    expect(readingModeLabel('explore')).toBe('Explore')
    expect(readingModeLabel('random')).toBe('Random')
  })

  it('falls back to the raw value and joins bandwidth with intent', () => {
    expect(readingModeLabel(null)).toBe('')
    expect(formatSessionMode({ bandwidth: 'light', intent: 'momentum' })).toBe('Light · Momentum')
    expect(
      formatSessionMode({ bandwidth: 'surprisingly-long-bandwidth', intent: 'explore' }),
    ).toBe('surprisingly-long-bandwidth · Explore')
    expect(formatSessionMode({ bandwidth: null, intent: 'random' })).toBe('Random')
    expect(formatSessionMode(null)).toBe('')
  })
})

describe('ReadingModeControl', () => {
  it.each([
    [{ bandwidth: 'light', intent: 'momentum' }, 'Light · Momentum'],
    [{ bandwidth: 'deep', intent: 'explore' }, 'Deep · Explore'],
    [{ bandwidth: 'balanced', intent: 'balanced' }, 'Balanced · Balanced'],
    [{ bandwidth: 'light', intent: 'random', source: 'manual', confidence: 0.92 }, 'Light · Random'],
  ] as [SessionModeState, string][])(
    'renders representative mode %j compactly as %s',
    (mode, expected) => {
      render(<ReadingModeControl mode={mode} />)

      const control = screen.getByTestId('reading-mode-control')
      expect(control).toHaveTextContent(expected)
      // Compact header-scale control: raw confidence must never be displayed.
      expect(control.textContent).not.toContain('0.92')
      expect(control.textContent).not.toMatch(/confidence/i)
    },
  )

  it('renders nothing for legacy bootstrap responses without session mode state', () => {
    const { container } = render(<ReadingModeControl mode={null} />)
    const empty = render(<ReadingModeControl mode={undefined} />)
    const noLabels = render(<ReadingModeControl mode={{ bandwidth: null, intent: null }} />)

    expect(container).toBeEmptyDOMElement()
    expect(empty.container).toBeEmptyDOMElement()
    expect(noLabels.container).toBeEmptyDOMElement()
  })

  it('opens the selector surface on tap, click, and keyboard activation', async () => {
    const user = userEvent.setup()
    const onOpenSelector = vi.fn()
    render(
      <ReadingModeControl
        mode={{ bandwidth: 'light', intent: 'momentum', source: 'inferred', confidence: 0.4 }}
        onOpenSelector={onOpenSelector}
      />,
    )

    const control = screen.getByRole('button', { name: 'Reading mode: Light · Momentum. Change reading mode' })
    expect(control).toHaveAttribute('aria-haspopup', 'dialog')
    expect(control).toHaveAccessibleName(/Light · Momentum/)

    await user.click(control)
    expect(onOpenSelector).toHaveBeenCalledTimes(1)

    await user.keyboard('{Enter}')
    expect(onOpenSelector).toHaveBeenCalledTimes(2)

    await user.keyboard(' ')
    expect(onOpenSelector).toHaveBeenCalledTimes(3)
  })

  it('degrades to a static status chip when no selector surface is wired yet', () => {
    render(<ReadingModeControl mode={{ bandwidth: 'deep', intent: 'familiar' }} />)

    expect(screen.getByTestId('reading-mode-control')).toHaveTextContent('Deep · Familiar')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('truncates long labels instead of crowding the die controls', () => {
    render(
      <ReadingModeControl
        mode={{
          bandwidth: 'extraordinarily-specific-inferred-light-bandwidth',
          intent: 'exploratory-momentum-adjacent',
        }}
        onOpenSelector={() => undefined}
      />,
    )

    const control = screen.getByRole('button')
    expect(control.className).toContain('max-w-[11rem]')
    expect(control.querySelector('span')?.className).toContain('truncate')
    expect(control.getAttribute('title')).toBe(
      'Reading mode: extraordinarily-specific-inferred-light-bandwidth · exploratory-momentum-adjacent',
    )
  })
})

describe('RollHeader reading-mode control integration', () => {
  it('shows the bootstrap session mode without dominating the header', () => {
    render(
      <RollHeader
        bootstrap={bootstrapWithMode({ bandwidth: 'light', intent: 'momentum', source: 'manual' })}
        {...headerBaseProps}
      />,
    )

    expect(screen.getByTestId('reading-mode-control')).toHaveTextContent('Light · Momentum')
    expect(screen.getAllByRole('button', { name: /d6/i }).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Pick manually' })).toBeInTheDocument()
  })

  it('stays synchronized when the bootstrap payload reports a manual mode change', () => {
    const { rerender } = render(
      <RollHeader bootstrap={bootstrapWithMode({ bandwidth: 'light', intent: 'momentum' })} {...headerBaseProps} />,
    )
    expect(screen.getByTestId('reading-mode-control')).toHaveTextContent('Light · Momentum')

    rerender(
      <RollHeader
        bootstrap={bootstrapWithMode({ bandwidth: 'deep', intent: 'random', source: 'manual' })}
        {...headerBaseProps}
      />,
    )
    expect(screen.getByTestId('reading-mode-control')).toHaveTextContent('Deep · Random')
  })

  it('omits the control entirely for legacy bootstrap payloads without mode state', () => {
    render(<RollHeader bootstrap={bootstrapWithMode(undefined)} {...headerBaseProps} />)

    expect(screen.queryByTestId('reading-mode-control')).not.toBeInTheDocument()
  })
})
