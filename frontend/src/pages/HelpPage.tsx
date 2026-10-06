import React, { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { requestSemanticScroll } from '../scroll/scrollCoordinator'
import { GLOSSARY_TERMS } from '../utils/glossaryTerms'

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
 * Visible permalink for one glossary definition (#3146).
 *
 * Deep links used to be guesswork: nothing on the card exposed the anchor, and
 * the anchor disagreed with the displayed term, so a copied `#series` style link
 * silently did nothing. This renders the canonical anchor as a real link —
 * copyable through the browser's own link affordances — and copies the absolute
 * deep link on activation for one-click sharing.
 */
function GlossaryPermalink({ id, term }: { id: string; term: string }) {
  const [status, setStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const permalink = `/glossary#${id}`

  async function copyPermalink() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${permalink}`)
      setStatus('copied')
    } catch {
      setStatus('failed')
    }
  }

  return (
    <>
      <Link
        to={permalink}
        onClick={() => {
          void copyPermalink()
        }}
        aria-label={`Copy link to ${term} definition`}
        title={`Copy link to ${term} definition`}
        data-testid="glossary-permalink"
        data-status={status}
        className="shrink-0 rounded px-1 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
      >
        #
      </Link>
      <span aria-live="polite" data-testid="glossary-permalink-status" className="sr-only">
        {status === 'copied'
          ? `Link to ${term} copied to clipboard.`
          : status === 'failed'
            ? `Could not copy the ${term} link. Copy it from the address bar instead.`
            : ''}
      </span>
    </>
  )
}

export default function HelpPage() {
  useGlossaryAnchorScroll()
  return (
    <section aria-label="Help and glossary" className="pt-4 pb-12 w-full" data-testid="glossary-list">
      <h1 className="text-2xl font-bold mb-4">Glossary</h1>
      <p className="text-sm text-stone-600 mb-6">Definitions for every reader-facing concept in ComicPile. 1–2 sentence explanations, mobile-friendly layout.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {GLOSSARY_TERMS.map((d) => (
          <div key={d.id} id={d.id} className="p-4 border rounded-lg bg-white/80 shadow-sm">
            {(d.aliases ?? []).map((alias) => (
              <span key={alias} id={alias} aria-hidden="true" className="sr-only" data-testid="glossary-anchor-alias" />
            ))}
            <div className="mb-2 flex items-start justify-between gap-2">
              <div className="text-sm font-semibold uppercase tracking-widest text-stone-600" data-testid="glossary-term">{d.term}</div>
              <GlossaryPermalink id={d.id} term={d.term} />
            </div>
            <div className="text-sm text-stone-700" data-testid="glossary-definition">{d.def}</div>
          </div>
        ))}
      </div>
    </section>
  )
}