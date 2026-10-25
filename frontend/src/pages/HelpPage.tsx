import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { requestSemanticScroll } from '../scroll/scrollCoordinator'
import { GLOSSARY_TERMS, type GlossaryTerm } from '../utils/glossaryTerms'

// Simple, static glossary help page for core app concepts.
// This is intentionally content-forward and does not touch backend.
// Definition content and the canonical anchor contract live in
// `utils/glossaryTerms.ts` so the anchor for a term can never drift from the
// term the reader sees (issue #3146).

/**
 * Scrolls the glossary to a definition when the page is opened through a
 * cross-link such as `/glossary#crossover`. Defers two animation frames so it
 * runs after the app's route-level scroll restoration, and routes the anchor
 * scroll through the scroll coordinator (#2582) so it additionally defers
 * while a route restore is still settling instead of racing it.
 */
function useGlossaryAnchorScroll(): void {
  const location = useLocation()
  useEffect(() => {
    const id = location.hash.slice(1)
    if (!id) return

    let frame = 0
    let cancelled = false
    const scrollToTerm = () => {
      if (cancelled) return
      requestSemanticScroll(() => {
        if (cancelled) return
        const target = document.getElementById(id)
        if (target) target.scrollIntoView({ block: 'start', behavior: 'auto' })
      })
    }
    frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(scrollToTerm)
    })
    return () => {
      cancelled = true
      window.cancelAnimationFrame(frame)
    }
  }, [location.hash])
}

/**
 * How long a glossary permalink confirmation stays on screen (#3603).
 *
 * The confirmation is deliberately short-lived: it answers "did that copy
 * work?", it is not a persistent status. One interval governs both the visible
 * and the announced state so a reader never sees one while hearing another.
 */
export const GLOSSARY_PERMALINK_FEEDBACK_MS = 3000

/** Clipboard outcome for the permalink a reader activated most recently. */
type GlossaryPermalinkCopyStatus = 'copied' | 'failed'

/** The one permalink confirmation currently owned by the page. */
type GlossaryPermalinkFeedback = {
  termId: string
  term: string
  status: GlossaryPermalinkCopyStatus
}

/** Canonical relative deep link for one glossary definition. */
function glossaryPermalinkPath(id: string): string {
  return `/glossary#${id}`
}

/**
 * Write a permalink and report what actually happened (#3603).
 *
 * The result is a status, never a thrown error: the caller needs a truthful
 * "did not copy" state rather than an unhandled rejection, and the browser's own
 * permission/insecure-context failures must not be swallowed silently.
 */
async function writePermalinkToClipboard(
  permalink: string,
): Promise<GlossaryPermalinkCopyStatus> {
  try {
    await navigator.clipboard.writeText(`${window.location.origin}${permalink}`)
    return 'copied'
  } catch {
    return 'failed'
  }
}

/**
 * Single-owner copy confirmation for the glossary permalink controls (#3603).
 *
 * Confirmation used to live in each card's own local state, so every term a
 * reader ever copied kept a `data-status="copied"` link and a hidden success
 * announcement while nothing visible confirmed the copy at all. Hoisting the
 * state to the page makes "the most recently copied term" representable:
 * activating a second permalink replaces the first one's state instead of
 * adding to it.
 *
 * Every activation is sequenced. A clipboard write that resolves late for a
 * superseded term is dropped instead of overwriting the newer confirmation, and
 * an already-queued expiry can only retire the confirmation it created. That is
 * what keeps rapid A → B → A activation truthful.
 */
function useGlossaryPermalinkFeedback(): {
  feedback: GlossaryPermalinkFeedback | null
  copyPermalink: (termId: string, term: string, permalink: string) => void
} {
  const [feedback, setFeedback] = useState<GlossaryPermalinkFeedback | null>(null)
  const timeoutRef = useRef<number | null>(null)
  const sequenceRef = useRef(0)
  const mountedRef = useRef(true)

  const clearPendingExpiry = useCallback(() => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      clearPendingExpiry()
    }
  }, [clearPendingExpiry])

  const copyPermalink = useCallback(
    (termId: string, term: string, permalink: string) => {
      sequenceRef.current += 1
      const sequence = sequenceRef.current
      clearPendingExpiry()
      // The newly activated term owns the confirmation slot from this moment, so
      // the previous term's visible and announced state clears immediately
      // rather than lingering until the new write settles.
      setFeedback(null)

      void writePermalinkToClipboard(permalink).then((status) => {
        if (!mountedRef.current || sequenceRef.current !== sequence) return
        setFeedback({ termId, term, status })
        timeoutRef.current = window.setTimeout(() => {
          timeoutRef.current = null
          setFeedback((current) => (sequenceRef.current === sequence ? null : current))
        }, GLOSSARY_PERMALINK_FEEDBACK_MS)
      })
    },
    [clearPendingExpiry],
  )

  return { feedback, copyPermalink }
}

/**
 * Visible permalink for one glossary definition (#3146).
 *
 * Deep links used to be guesswork: nothing on the card exposed the anchor, and
 * the anchor disagreed with the displayed term, so a copied `#series` style link
 * silently did nothing. This renders the canonical anchor as a real link —
 * copyable through the browser's own link affordances — and copies the absolute
 * deep link on activation for one-click sharing.
 *
 * The copy outcome is reported upward rather than held here (#3603): the page
 * owns the single active confirmation, so an earlier term cannot keep a stale
 * "copied" state or announcement after a later term is copied.
 */
function GlossaryPermalink({
  term,
  permalink,
  copyStatus,
  onActivate,
}: {
  term: string
  permalink: string
  /** This term's copy outcome, or null when another term owns the confirmation. */
  copyStatus: GlossaryPermalinkCopyStatus | null
  onActivate: () => void
}) {
  return (
    <div className="flex shrink-0 flex-wrap items-center justify-end gap-x-1.5 gap-y-0.5">
      <Link
        to={permalink}
        onClick={onActivate}
        aria-label={`Copy link to ${term} definition`}
        title={`Copy link to ${term} definition`}
        data-testid="glossary-permalink"
        data-status={copyStatus ?? 'idle'}
        className="shrink-0 rounded px-1 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
      >
        #
      </Link>
      {copyStatus ? (
        // The visible confirmation is decorative for assistive tech: the page's
        // single polite live region below already announces the same outcome in
        // a full sentence, and duplicating it would read the status twice.
        <span
          aria-hidden="true"
          data-testid="glossary-permalink-feedback"
          data-status={copyStatus}
          className={`whitespace-nowrap text-[11px] font-semibold ${
            copyStatus === 'copied'
              ? 'text-[var(--theme-success)]'
              : 'text-[var(--theme-error)]'
          }`}
        >
          {copyStatus === 'copied' ? 'Copied!' : 'Copy failed'}
        </span>
      ) : null}
    </div>
  )
}

export default function HelpPage() {
  const location = useLocation()
  useGlossaryAnchorScroll()
  const { feedback, copyPermalink } = useGlossaryPermalinkFeedback()
  const targetId = location.hash.slice(1)

  /**
   * The one screen-reader announcement for the active permalink confirmation.
   *
   * It names the term and the copied link, and it is the only live region on the
   * page: per-card regions accumulated one stale announcement per definition the
   * reader had ever copied (#3680).
   */
  const copyAnnouncement =
    feedback === null
      ? ''
      : feedback.status === 'copied'
        ? `Link to ${feedback.term} copied to clipboard.`
        : `Could not copy the ${feedback.term} link. Copy it from the address bar instead.`

  /**
   * Whether this card is the definition the URL fragment points at.
   *
   * A deep link identifies its target by fragment, so the card that owns that
   * fragment has to be the one the reader sees highlighted (#3681). Retired
   * alias ids stay resolvable inside the same card, so an old deep link still
   * highlights the definition the reader expects.
   */
  function isHighlighted(d: GlossaryTerm): boolean {
    if (!targetId) return false
    return d.id === targetId || (d.aliases?.includes(targetId) ?? false)
  }

  return (
    <section aria-label="Help and glossary" className="pt-4 pb-12 w-full" data-testid="glossary-list">
      <h1 className="text-2xl font-bold mb-4">Glossary</h1>
      <p className="text-sm text-stone-600 mb-6">Definitions for every reader-facing concept in ComicPile. 1–2 sentence explanations, mobile-friendly layout.</p>
      <span aria-live="polite" data-testid="glossary-permalink-status" className="sr-only">
        {copyAnnouncement}
      </span>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {GLOSSARY_TERMS.map((d) => {
          const highlighted = isHighlighted(d)
          const permalink = glossaryPermalinkPath(d.id)
          return (
            <div
              key={d.id}
              id={d.id}
              aria-current={highlighted ? 'location' : undefined}
              className={`p-4 border rounded-lg bg-white/80 shadow-sm transition-all duration-300 motion-reduce:transition-none ${
                highlighted ? 'ring-2 ring-[var(--theme-focus-ring)] border-[var(--theme-focus-ring)]' : ''
              }`}
            >
              {(d.aliases ?? []).map((alias) => (
                <span key={alias} id={alias} aria-hidden="true" className="sr-only" data-testid="glossary-anchor-alias" />
              ))}
              <div className="mb-2 flex items-start justify-between gap-2">
                <div className="min-w-0 text-sm font-semibold uppercase tracking-widest text-stone-600" data-testid="glossary-term">{d.term}</div>
                <GlossaryPermalink
                  term={d.term}
                  permalink={permalink}
                  copyStatus={feedback?.termId === d.id ? feedback.status : null}
                  onActivate={() => copyPermalink(d.id, d.term, permalink)}
                />
              </div>
              <div className="text-sm text-stone-700" data-testid="glossary-definition">{d.def}</div>
            </div>
          )
        })}
      </div>
    </section>
  )
}