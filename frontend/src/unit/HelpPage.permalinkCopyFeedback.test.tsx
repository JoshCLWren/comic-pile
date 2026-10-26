import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import HelpPage, { GLOSSARY_PERMALINK_FEEDBACK_MS } from '../pages/HelpPage'

/**
 * Issue #3603 acceptance contract (consolidating #3680).
 *
 * The glossary permalink control copied the deep link and announced it, but a
 * sighted reader saw nothing happen. Confirmation also lived in each card's own
 * state, so every term ever copied kept `data-status="copied"` plus a stale
 * hidden announcement while no visible confirmation was rendered anywhere.
 *
 * The contract is now:
 *  1. a successful clipboard write shows a short visible inline `Copied!` on the
 *     activated term and announces it once;
 *  2. the most recently copied term alone owns the confirmation — copying a
 *     second term clears the first term's visible, `data-status`, and announced
 *     state;
 *  3. rapid A → B → A activation never lets an earlier expiry clear the newest
 *     confirmation;
 *  4. a rejected clipboard write reports an honest failure, never `Copied!`;
 *  5. the confirmation expires after a short defined interval and does not
 *     survive unmount;
 *  6. deep links, highlight behavior, accessible names, and keyboard focus are
 *     unchanged.
 */

/**
 * Clipboard double used by the raw-click activation helper below.
 *
 * `userEvent.setup()` installs its own clipboard stub that replaces this one, so
 * user-event tests spy on `navigator.clipboard.writeText` after `setup()` — the
 * same pattern the #3146 permalink coverage uses.
 */
let rawWriteText: ReturnType<typeof vi.fn>

beforeEach(() => {
  rawWriteText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: rawWriteText, readText: vi.fn().mockResolvedValue('') },
  })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function renderGlossary(path = '/glossary') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HelpPage />
    </MemoryRouter>,
  )
}

function permalinkFor(term: string): HTMLElement {
  return screen.getByRole('link', { name: `Copy link to ${term} definition` })
}

function cardFor(term: string): HTMLElement {
  const permalink = permalinkFor(term)
  const card = permalink.closest('[id]')
  expect(card, `expected the ${term} permalink to sit on a definition card`).not.toBeNull()
  // SAFETY: expect above asserted non-null, so the cast is safe.
  return card as HTMLElement
}

function feedbackIn(term: string): HTMLElement | null {
  return within(cardFor(term)).queryByTestId('glossary-permalink-feedback')
}

function statusRegion(): HTMLElement {
  return screen.getByTestId('glossary-permalink-status')
}

/**
 * Activate a permalink without user-event's own async scheduling.
 *
 * The expiry cases need fake timers, and user-event's internal delays only
 * resolve against real ones. A synchronous click wrapped in an async `act`
 * flushes the clipboard promise the component awaits, which is the behavior
 * under test.
 */
async function activate(term: string): Promise<void> {
  await act(async () => {
    fireEvent.click(permalinkFor(term))
  })
}

describe('glossary permalink copy feedback (issue #3603)', () => {
  it('shows a visible inline Copied! confirmation on the activated term', async () => {
    const user = userEvent.setup()
    renderGlossary()

    await user.click(permalinkFor('Series'))

    const permalink = permalinkFor('Series')
    await vi.waitFor(() => expect(permalink).toHaveAttribute('data-status', 'copied'))

    const feedback = feedbackIn('Series')
    expect(feedback).not.toBeNull()
    expect(feedback).toHaveTextContent('Copied!')
    expect(feedback).toHaveAttribute('data-status', 'copied')
    // The visible badge is adjacent to the control it confirms, so a reader
    // connects the confirmation to the term they just activated.
    expect(permalink.parentElement).toContainElement(feedback)
    // Sighted and screen-reader feedback must not be duplicated: the single
    // polite region owns the spoken announcement.
    expect(feedback).toHaveAttribute('aria-hidden', 'true')
    expect(statusRegion()).toHaveTextContent('Link to Series copied to clipboard.')
  })

  it('keeps one live region for the whole page instead of one per card', () => {
    renderGlossary()

    expect(screen.getAllByTestId('glossary-permalink-status')).toHaveLength(1)
    expect(document.querySelectorAll('[aria-live]')).toHaveLength(1)
    expect(statusRegion()).toHaveAttribute('aria-live', 'polite')
    expect(statusRegion()).toBeEmptyDOMElement()
  })

  it('gives the confirmation to the newest copied term only', async () => {
    const user = userEvent.setup()
    renderGlossary()

    await user.click(permalinkFor('Series'))
    await vi.waitFor(() => expect(permalinkFor('Series')).toHaveAttribute('data-status', 'copied'))

    await user.click(permalinkFor('Blocked'))
    await vi.waitFor(() => expect(permalinkFor('Blocked')).toHaveAttribute('data-status', 'copied'))

    // Term A keeps no stale visible, data-status, or announced success state.
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'idle')
    expect(feedbackIn('Series')).toBeNull()
    expect(feedbackIn('Blocked')).toHaveTextContent('Copied!')
    expect(statusRegion()).toHaveTextContent('Link to Blocked copied to clipboard.')
    expect(statusRegion()).not.toHaveTextContent('Series')
    expect(document.querySelectorAll('[data-testid="glossary-permalink-feedback"]')).toHaveLength(1)
  })

  it('does not let an earlier confirmation expire the newest one', async () => {
    vi.useFakeTimers()
    renderGlossary()

    await activate('Series')
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'copied')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(GLOSSARY_PERMALINK_FEEDBACK_MS - 500)
    })

    await activate('Blocked')
    expect(permalinkFor('Blocked')).toHaveAttribute('data-status', 'copied')

    // Series' original deadline passes here; it must not retire Blocked's newer
    // confirmation.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
    expect(permalinkFor('Blocked')).toHaveAttribute('data-status', 'copied')
    expect(feedbackIn('Blocked')).toHaveTextContent('Copied!')

    // Rapid return to the first term restarts its own lifetime.
    await activate('Series')
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'copied')
    expect(permalinkFor('Blocked')).toHaveAttribute('data-status', 'idle')
    expect(feedbackIn('Blocked')).toBeNull()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(GLOSSARY_PERMALINK_FEEDBACK_MS - 1)
    })
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'copied')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'idle')
    expect(feedbackIn('Series')).toBeNull()
    expect(statusRegion()).toBeEmptyDOMElement()
  })

  it('drops a delayed clipboard result from a superseded term', async () => {
    let resolveFirst: (() => void) | null = null
    rawWriteText
      .mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockResolvedValueOnce(undefined)
    renderGlossary()

    await act(async () => {
      fireEvent.click(permalinkFor('Series'))
    })
    await act(async () => {
      fireEvent.click(permalinkFor('Blocked'))
    })

    // The newer copy settles first and owns the confirmation.
    expect(permalinkFor('Blocked')).toHaveAttribute('data-status', 'copied')

    // The superseded write settling late must not resurrect Series' state.
    expect(resolveFirst).not.toBeNull()
    await act(async () => {
      resolveFirst!()
    })
    expect(permalinkFor('Blocked')).toHaveAttribute('data-status', 'copied')
    expect(feedbackIn('Blocked')).toHaveTextContent('Copied!')
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'idle')
    expect(feedbackIn('Series')).toBeNull()
    expect(statusRegion()).toHaveTextContent('Link to Blocked copied to clipboard.')
  })

  it('reports an honest failure instead of claiming the link was copied', async () => {
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('clipboard denied'))
    renderGlossary()

    await user.click(permalinkFor('Blocked'))

    const permalink = permalinkFor('Blocked')
    await vi.waitFor(() => expect(permalink).toHaveAttribute('data-status', 'failed'))

    expect(feedbackIn('Blocked')).toHaveTextContent('Copy failed')
    expect(feedbackIn('Blocked')).toHaveAttribute('data-status', 'failed')
    expect(screen.queryByText('Copied!')).not.toBeInTheDocument()
    expect(statusRegion()).toHaveTextContent(
      'Could not copy the Blocked link. Copy it from the address bar instead.',
    )
    expect(statusRegion()).not.toHaveTextContent('copied to clipboard')
  })

  it('clears the confirmation after its short lifetime', async () => {
    vi.useFakeTimers()
    renderGlossary()

    await activate('Series')
    expect(feedbackIn('Series')).toHaveTextContent('Copied!')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(GLOSSARY_PERMALINK_FEEDBACK_MS)
    })

    expect(feedbackIn('Series')).toBeNull()
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'idle')
    expect(statusRegion()).toBeEmptyDOMElement()
  })

  it('keeps keyboard activation working and holds focus on the permalink', async () => {
    const user = userEvent.setup()
    const writeText = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockResolvedValue(undefined)
    renderGlossary()

    const permalink = permalinkFor('Die size')
    permalink.focus()
    expect(permalink).toHaveFocus()

    await user.keyboard('{Enter}')

    await vi.waitFor(() => expect(permalink).toHaveAttribute('data-status', 'copied'))
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/glossary#die-size`)
    expect(permalink).toHaveFocus()
    expect(feedbackIn('Die size')).toHaveTextContent('Copied!')
    // Activation still performs the deep-link navigation (#3146/#3681).
    expect(document.getElementById('die-size')).toHaveAttribute('aria-current', 'location')
  })

  it('does not leak the confirmation across unmount and remount', async () => {
    vi.useFakeTimers()
    const first = renderGlossary()

    await activate('Series')
    expect(feedbackIn('Series')).toHaveTextContent('Copied!')

    first.unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(GLOSSARY_PERMALINK_FEEDBACK_MS * 2)
    })

    renderGlossary()
    expect(feedbackIn('Series')).toBeNull()
    expect(permalinkFor('Series')).toHaveAttribute('data-status', 'idle')
    expect(statusRegion()).toBeEmptyDOMElement()
  })
})
