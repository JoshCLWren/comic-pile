/**
 * Issue #2712: Roll rating page chrome.
 *
 * The rating workspace is the approved visual contract, so the header resolves
 * to the same bounded shell and the same Comic/Decision tracks as the workspace
 * it frames, and the queue action carries the accessible name a reader would
 * expect rather than the decorative arrow glyph.
 *
 * These assertions encode rendered structure, not class aesthetics: which
 * element owns the accent rule, and which controls exist in each mode. The
 * non-rating cases matter as much as the rating ones — the rating view must not
 * unmount the die ladder or the manual-pick entry, which is what lets the die
 * view and its coverage stay intact.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { cast } from '../utils/cast'
import { RollFooter } from '../pages/RollPage/components/RollFooter'
import { RollHeader } from '../pages/RollPage/components/RollHeader'
import { resolveRollSelectedDie } from '../pages/RollPage/selectedDie'
import {
  ROLL_WORKSPACE_MAX_WIDTH,
  ROLL_WORKSPACE_TRACKS,
} from '../pages/RollPage/workspaceLayout'
import type { RollBootstrapResponse } from '../types/rollBootstrap'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/GlossaryLink', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// SAFETY: test fixture supplies only the fields the header component reads for session state
const BOOTSTRAP = cast<RollBootstrapResponse>({
  session_mode: null,
})

function headerProps(overrides: Partial<React.ComponentProps<typeof RollHeader>> = {}) {
  return {
    bootstrap: BOOTSTRAP,
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
    ...overrides,
  }
}

function renderHeader(overrides: Partial<React.ComponentProps<typeof RollHeader>> = {}) {
  return render(
    <MemoryRouter>
      <RollHeader {...headerProps(overrides)} />
    </MemoryRouter>,
  )
}

describe('Roll rating header chrome (#2712)', () => {
  it('anchors the title, subtitle, and accent rule to the workspace comic track', () => {
    renderHeader({ isRatingView: true, onBackToQueue: vi.fn() })

    expect(screen.getByTestId('roll-header-subtitle')).toHaveTextContent(
      'A random comic from your library',
    )

    const workspace = screen.getByTestId('roll-header-workspace')
    // Same bounded shell and same two-region split as the workspace itself, so
    // the header edges and the Comic/Decision division cannot drift apart.
    expect(workspace.className).toContain(ROLL_WORKSPACE_MAX_WIDTH)
    expect(workspace.className).toContain(ROLL_WORKSPACE_TRACKS)

    const rule = screen.getByTestId('roll-header-accent-rule')
    const comicCell = workspace.firstElementChild!
    // The rule belongs to the comic side: it shares the first track with the
    // title and stops at the division instead of running beneath the queue
    // action.
    expect(comicCell.contains(rule)).toBe(true)
    expect(comicCell.contains(screen.getByRole('heading', { name: 'Roll' }))).toBe(true)
    expect(comicCell.contains(screen.getByRole('button', { name: 'Back to queue' }))).toBe(false)
  })

  it('offers a queue action whose accessible name excludes the arrow glyph', async () => {
    const onBackToQueue = vi.fn()
    const user = userEvent.setup()
    renderHeader({ isRatingView: true, onBackToQueue })

    const action = screen.getByRole('button', { name: 'Back to queue' })
    expect(action).toHaveAttribute('data-testid', 'roll-back-to-queue')

    await user.click(action)
    expect(onBackToQueue).toHaveBeenCalledTimes(1)
  })

  // #4352: die selection is render-derived (`resolveRollSelectedDie`), not
  // effect-synced. The header receives the derived die as `currentDie`.
  it('uses the scoped die (#4352)', () => {
    const selectedDie = resolveRollSelectedDie(
      { die: 20, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 20, last_roll: null },
    )
    expect(selectedDie).toBe(20)
    renderHeader({
      currentDie: selectedDie,
      dieState: { die: 20, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 20, last_roll: null },
    })
    expect(screen.getByRole('button', { name: 'd20' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('defaults to d6 while scoped state is unsettled (#4352 contract-after)', () => {
    const selectedDie = resolveRollSelectedDie(undefined)
    expect(selectedDie).toBe(6)
    renderHeader({ currentDie: selectedDie, dieState: null })
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('defaults to d6 when scoped state is null (#4352 contract-after)', () => {
    const selectedDie = resolveRollSelectedDie(null)
    expect(selectedDie).toBe(6)
    renderHeader({ currentDie: selectedDie, dieState: null })
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('defaults to d6 when scoped state is absent (#4352 contract-after)', () => {
    expect(resolveRollSelectedDie(undefined)).toBe(6)
    expect(resolveRollSelectedDie(null)).toBe(6)
  })

  it('defaults to d6 when the scoped query errored (#4352 contract-after)', () => {
    // RollPage maps `isScopedDieStateError` to `undefined` scoped state
    // (index.tsx) so the scoped-only derivation falls back to d6.
    const selectedDie = resolveRollSelectedDie(undefined)
    expect(selectedDie).toBe(6)
    renderHeader({ currentDie: selectedDie, dieState: null })
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('shows the new die after die-state invalidation without a bootstrap refetch (#4352)', () => {
    // `useSetDie` invalidates the scoped die-state query; the header must
    // track the refetched `dieState` while `bootstrap` stays byte-identical.
    const before = resolveRollSelectedDie(
      { die: 6, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
    )
    const { rerender } = renderHeader({
      currentDie: before,
      dieState: { die: 6, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
    })
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'true')

    const after = resolveRollSelectedDie(
      { die: 20, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
    )
    expect(after).toBe(20)
    rerender(
      <MemoryRouter>
        <RollHeader
          {...headerProps({
            currentDie: after,
            dieState: { die: 20, ladder: [2, 4, 6, 8, 10, 12, 20], default_die: 6, last_roll: null },
          })}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('button', { name: 'd20' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('drives the ladder buttons from the scoped ladder when present (#4719)', () => {
    renderHeader({ dieState: { die: 8, ladder: [4, 8], default_die: 6, last_roll: null } })
    expect(screen.getByRole('button', { name: 'd8' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'd4' })).toHaveAttribute('aria-pressed', 'false')
    // The static ladder no longer supplies the header when scoped data settles.
    expect(screen.queryByRole('button', { name: 'd6' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'd20' })).not.toBeInTheDocument()
  })

  it('falls back to the static ladder when the scoped ladder is empty (#4719)', () => {
    renderHeader({ dieState: { die: 6, ladder: [], default_die: 6, last_roll: null } })
    expect(screen.getByRole('button', { name: 'd6' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'd20' })).toBeInTheDocument()
  })

  it('leaves the die view header chrome untouched', () => {
    const { container } = renderHeader({ isRatingView: false, onBackToQueue: vi.fn() })

    expect(screen.queryByTestId('roll-header-subtitle')).not.toBeInTheDocument()
    expect(screen.queryByTestId('roll-header-accent-rule')).not.toBeInTheDocument()
    expect(screen.queryByTestId('roll-back-to-queue')).not.toBeInTheDocument()

    // The die controls belong to the die view. The rating chrome is an addition
    // to that view, never a replacement for controls the die view still needs.
    expect(screen.getByRole('button', { name: 'Pick manually' })).toBeInTheDocument()
    expect(container.querySelector('[data-roll-die-selector="primary"]')).not.toBeNull()
    // The die is event-derived, so there is no Auto/Manual segment (#4353).
    expect(screen.queryByRole('button', { name: 'Auto' })).not.toBeInTheDocument()
  })
})

describe('Roll rating footer (#2712)', () => {
  it('shows the dice encouragement and brand tagline at desktop widths only', () => {
    render(<RollFooter />)

    const footer = screen.getByTestId('roll-footer')
    // Desktop-only: a stacked or stacked-over-actions footer at constrained
    // widths would push the rating actions out of the task view.
    expect(footer.className).toContain('hidden')
    expect(footer.className).toContain('lg:block')
    expect(footer.className).toContain('border-t')

    expect(screen.getByText('Enjoy the next adventure.')).toBeInTheDocument()
    expect(screen.getByText('Read more comics.')).toBeInTheDocument()
    expect(screen.getByText('Comic Pile')).toBeInTheDocument()
    expect(
      screen.getByText('Your collection. New discoveries. Greater stories.'),
    ).toBeInTheDocument()

    const content = footer.firstElementChild!
    expect(content.className).toContain(ROLL_WORKSPACE_MAX_WIDTH)
  })
})