import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { RollHeader } from '../pages/RollPage/components/RollHeader'
import { ReadingModeControl } from '../pages/RollPage/components/ReadingModeControl'
import type { RollState } from '../types/rollState'
import {
  formatReadingMode,
  readingModeLabel,
  type ReadingModeDisplay,
} from '../types/readingMode'

const rollState: RollState = {
  pending_thread_id: null,
  last_rolled_result: null,
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
}

const headerBaseProps = {
  currentDie: 6,
  dieSize: 6,
  displayDie: 6 as const,
  snoozedThreads: [],
  pool: [],
  isRatingView: false,
  setDiePending: false,
  onSetDie: vi.fn(),
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
    expect(formatReadingMode({ bandwidth: 'light', intent: 'momentum' })).toBe('Light · Momentum')
    expect(formatReadingMode({
      bandwidth: 'surprisingly-long-bandwidth',
      intent: 'explore',
    })).toBe('surprisingly-long-bandwidth · Explore')
    expect(formatReadingMode({ bandwidth: null, intent: 'random' })).toBe('Random')
    expect(formatReadingMode(null)).toBe('')
  })
})

describe('ReadingModeControl', () => {
  it.each([
    [{ bandwidth: 'light', intent: 'momentum' }, 'Light · Momentum'],
    [{ bandwidth: 'deep', intent: 'explore' }, 'Deep · Explore'],
    [{ bandwidth: 'balanced', intent: 'balanced' }, 'Balanced · Balanced'],
    [{ bandwidth: 'light', intent: 'random', source: 'manual', confidence: 0.92 }, 'Light · Random'],
  ] satisfies [ReadingModeDisplay, string][])(
    'renders representative mode %j compactly as %s',
    (mode, expected) => {
      render(<ReadingModeControl mode={mode} />)
      const control = screen.getByTestId('reading-mode-control')
      expect(control).toHaveTextContent(expected)
      expect(control.textContent).not.toContain('0.92')
      expect(control.textContent).not.toMatch(/confidence/i)
    },
  )

  it('renders nothing when the scoped mode has no labels', () => {
    const { container } = render(<ReadingModeControl mode={{ bandwidth: null, intent: null }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('is a read-only status chip, not a retired mode selector', () => {
    render(<ReadingModeControl mode={{ bandwidth: 'light', intent: 'momentum' }} />)
    const control = screen.getByTestId('reading-mode-control')
    expect(control.tagName).toBe('SPAN')
    expect(control).toHaveAttribute('title', 'Reading mode: Light · Momentum')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('RollHeader scoped reading-mode integration', () => {
  it('shows the canonical mode without putting session state in RollState', () => {
    render(
      <MemoryRouter>
        <RollHeader
          bootstrap={rollState}
          readingMode={{ bandwidth: 'light', intent: 'momentum', source: 'manual' }}
          {...headerBaseProps}
        />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('reading-mode-control')).toHaveTextContent('Light · Momentum')
    expect(screen.getByRole('button', { name: 'Pick manually' })).toBeInTheDocument()
  })

  it('omits the chip when scoped reading mode is unavailable', () => {
    render(
      <MemoryRouter>
        <RollHeader bootstrap={rollState} {...headerBaseProps} />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('reading-mode-control')).not.toBeInTheDocument()
  })
})
