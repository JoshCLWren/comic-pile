import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { DICE_LADDER } from '../components/diceLadder'
import { RollHeader } from '../pages/RollPage/components/RollHeader'
import type { RollBootstrapResponse, SessionMode } from '../types/rollBootstrap'

const ACTIVE_FILL = 'bg-[var(--theme-primary-action)]'

function emptySessionMode(): SessionMode {
  return {
    active_bandwidth: null,
    predicted_bandwidth: null,
    bandwidth_confidence: null,
    bandwidth_source: null,
    bandwidth_version: null,
    active_intent: null,
    predicted_intent: null,
    intent_confidence: null,
    intent_source: null,
    intent_version: null,
    session_mode_correction_guidance: null,
  }
}

function makeBootstrap(overrides: Partial<RollBootstrapResponse> = {}): RollBootstrapResponse {
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
    skipped_thread_ids: [],
    skipped_threads: [],
    blocked_count: 0,
    blocked_threads: [],
    stale_thread_count: 0,
    stale_thread: null,
    session_mode: emptySessionMode(),
    ...overrides,
  }
}

function balancedSessionMode(): SessionMode {
  return {
    active_bandwidth: 'balanced',
    predicted_bandwidth: 'balanced',
    bandwidth_confidence: null,
    bandwidth_source: 'inferred',
    bandwidth_version: null,
    active_intent: 'balanced',
    predicted_intent: null,
    intent_confidence: null,
    intent_source: null,
    intent_version: null,
    session_mode_correction_guidance: null,
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

function renderHeader(bootstrap: RollBootstrapResponse, currentDie = 6) {
  return render(
    <MemoryRouter>
      <RollHeader bootstrap={bootstrap} {...headerBaseProps} currentDie={currentDie} />
    </MemoryRouter>,
  )
}

describe('roll-mode control group (issue #2304): visual state grammar', () => {
  it('marks exactly one roll-mode control with the solid active treatment on the mobile row', () => {
    renderHeader(makeBootstrap({ current_die: 4, session_mode: balancedSessionMode() }), 4)

    const dieControl = screen.getByRole('button', { name: /current die d4, automatic mode/i })
    expect(dieControl.className).toContain(ACTIVE_FILL)
    expect(dieControl.className).toContain('text-stone-900')

    const pickManually = screen.getByRole('button', { name: /pick manually/i })
    expect(pickManually.className).not.toContain(ACTIVE_FILL)

    const chip = screen.getByTestId('reading-mode-control')
    expect(chip.className).not.toContain(ACTIVE_FILL)
  })

  it('renders Pick Manually as a non-solid outlined action, not a selected state', () => {
    renderHeader(makeBootstrap({ session_mode: balancedSessionMode() }))

    const pickManually = screen.getByRole('button', { name: /pick manually/i })
    expect(pickManually).toHaveAttribute('aria-haspopup', 'dialog')
    expect(pickManually.className).toContain('bg-[var(--theme-bg-panel)]')
    expect(pickManually.className).toContain('border-[var(--theme-border)]')
    expect(pickManually.className).not.toContain(ACTIVE_FILL)
  })

  it('keeps the balanced reading-mode chip on the quiet inactive convention', () => {
    renderHeader(makeBootstrap({ session_mode: balancedSessionMode() }))

    const chip = screen.getByTestId('reading-mode-control')
    expect(chip).toHaveTextContent('Balanced')
    expect(chip.className).toContain('bg-[var(--theme-bg-panel)]')
    expect(chip.className).toContain('border-[var(--theme-border)]')
    expect(chip.className).toContain('text-[var(--theme-text-muted)]')
  })

  it('shares the compact control-family shape between the die control and the chip', () => {
    renderHeader(makeBootstrap({ session_mode: balancedSessionMode() }))

    const dieControl = screen.getByRole('button', { name: /current die d6, automatic mode/i })
    const chip = screen.getByTestId('reading-mode-control')
    expect(dieControl.className).toContain('min-h-11')
    expect(dieControl.className).toContain('rounded-xl')
    expect(chip.className).toContain('min-h-11')
    expect(chip.className).toContain('rounded-xl')
  })
})

describe('roll-mode control group (issue #2304): accessible active-mode state', () => {
  it('reports pressed on the ladder Auto segment only while automatic mode is active', () => {
    renderHeader(makeBootstrap({ current_die: 4 }), 4)

    const auto = screen.getByRole('button', { name: 'Auto' })
    expect(auto).toHaveAttribute('aria-pressed', 'true')
    const activeDie = screen.getByRole('button', { name: 'd4' })
    expect(activeDie).toHaveAttribute('aria-pressed', 'true')
  })

  it('flips the ladder to the pinned die and unpresses Auto in manual mode', () => {
    render(
      <MemoryRouter>
        <RollHeader
          bootstrap={makeBootstrap({ current_die: 4, manual_die: 8 })}
          {...headerBaseProps}
          currentDie={8}
        />
      </MemoryRouter>,
    )

    const auto = screen.getByRole('button', { name: 'Auto' })
    expect(auto).toHaveAttribute('aria-pressed', 'false')
    expect(auto).toHaveAttribute('title', 'Exit manual mode (currently d8)')

    const pinned = screen.getByRole('button', { name: 'd8' })
    expect(pinned).toHaveAttribute('aria-pressed', 'true')

    for (const die of DICE_LADDER) {
      if (die === 8) continue
      expect(screen.getByRole('button', { name: `d${die}` })).toHaveAttribute('aria-pressed', 'false')
    }
  })

  it('reports the actual die mode in the mobile control accessible name', () => {
    renderHeader(makeBootstrap({ current_die: 4 }), 4)
    expect(screen.getByRole('button', { name: 'Current die d4, automatic mode' })).toBeInTheDocument()
  })
})