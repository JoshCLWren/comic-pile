import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { DICE_LADDER } from '../components/diceLadder'
import { RollHeader } from '../pages/RollPage/components/RollHeader'
import type { RollState } from '../types/rollState'
import type { ReadingModeDisplay } from '../types/readingMode'

const ACTIVE_FILL = 'bg-[var(--theme-primary-action)]'
const balancedMode: ReadingModeDisplay = { bandwidth: 'balanced', intent: 'balanced' }

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

function renderHeader(currentDie = 6, readingMode: ReadingModeDisplay | null = null) {
  return render(
    <MemoryRouter>
      <RollHeader
        bootstrap={rollState}
        readingMode={readingMode}
        {...headerBaseProps}
        currentDie={currentDie}
      />
    </MemoryRouter>,
  )
}

describe('roll-mode control group (issue #2304): visual state grammar', () => {
  it('marks exactly one roll-mode control with the solid active treatment on the mobile row', () => {
    renderHeader(4, balancedMode)
    const dieControl = screen.getByRole('button', { name: /^current die d4$/i })
    expect(dieControl.className).toContain(ACTIVE_FILL)
    expect(dieControl.className).toContain('text-stone-900')
    expect(screen.getByRole('button', { name: /pick manually/i }).className).not.toContain(ACTIVE_FILL)
    expect(screen.getByTestId('reading-mode-control').className).not.toContain(ACTIVE_FILL)
  })

  it('renders Pick Manually as a non-solid outlined action, not a selected state', () => {
    renderHeader()
    const pickManually = screen.getByRole('button', { name: /pick manually/i })
    expect(pickManually).toHaveAttribute('aria-haspopup', 'dialog')
    expect(pickManually.className).toContain('bg-[var(--theme-bg-panel)]')
    expect(pickManually.className).toContain('border-[var(--theme-border)]')
    expect(pickManually.className).not.toContain(ACTIVE_FILL)
  })

  it('keeps the reading-mode chip on the quiet inactive convention', () => {
    renderHeader(6, balancedMode)
    const chip = screen.getByTestId('reading-mode-control')
    expect(chip).toHaveTextContent('Balanced')
    expect(chip.className).toContain('bg-[var(--theme-bg-panel)]')
    expect(chip.className).toContain('border-[var(--theme-border)]')
    expect(chip.className).toContain('text-[var(--theme-text-muted)]')
  })

  it('shares the compact control-family shape between the die control and the chip', () => {
    renderHeader(6, balancedMode)
    const dieControl = screen.getByRole('button', { name: /^current die d6$/i })
    const chip = screen.getByTestId('reading-mode-control')
    expect(dieControl.className).toContain('min-h-11')
    expect(dieControl.className).toContain('rounded-xl')
    expect(chip.className).toContain('min-h-11')
    expect(chip.className).toContain('rounded-xl')
  })
})

describe('roll-mode control group (issue #2304): accessible active-mode state', () => {
  it('presses only the current die segment and renders no Auto segment (#4353)', () => {
    renderHeader(4)
    expect(screen.queryByRole('button', { name: 'Auto' })).toBeNull()
    expect(screen.getByRole('button', { name: 'd4' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('presses the event-derived die after a manual choice, with no sticky mode (#4279)', () => {
    renderHeader(8)
    expect(screen.queryByRole('button', { name: 'Auto' })).toBeNull()
    expect(screen.getByRole('button', { name: 'd8' })).toHaveAttribute('aria-pressed', 'true')
    for (const die of DICE_LADDER) {
      if (die === 8) continue
      expect(screen.getByRole('button', { name: `d${die}` })).toHaveAttribute('aria-pressed', 'false')
    }
  })

  it('names the mobile die control for the current die without a mode suffix', () => {
    renderHeader(4)
    expect(screen.getByRole('button', { name: 'Current die d4' })).toBeInTheDocument()
  })
})
