import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { CubeIcon, UserIcon } from '@heroicons/react/24/outline'
import { useQuery } from '@tanstack/react-query'
import { demoApi, type DemoApi } from '../services/api-demo'
import { queryKeys } from '../query/queryKeys'

const RATING_MIN = 0.5
const RATING_MAX = 5
const RATING_STEP = 0.5
const DEFAULT_RATING = 4

// Mirrors the die ladder the landing page describes: a 4.0 or higher rating
// promotes a series, anything lower defers it.
const QUEUE_PROMOTION_THRESHOLD = 4

interface DemoRollPageProps {
  /** Injectable demo service seam so tests can supply a controllable transport. */
  api?: DemoApi
}

export default function DemoRollPage({ api = demoApi }: DemoRollPageProps) {
  const [rating, setRating] = useState(DEFAULT_RATING)
  const [rated, setRated] = useState(false)

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: queryKeys.demo.roll(),
    queryFn: () => api.roll(),
  })

  const ratingFillPct = ((rating - RATING_MIN) / (RATING_MAX - RATING_MIN)) * 100

  if (isPending) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]" data-testid="demo-roll-loading">
        <div className="text-center space-y-3">
          <CubeIcon className="h-10 w-10 mx-auto animate-spin text-[var(--theme-comic-accent)]" aria-hidden="true" />
          <p className="text-sm font-bold text-[var(--theme-text-muted)]">Seeding sample roll…</p>
        </div>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]" data-testid="demo-roll-error">
        <div className="surface-panel max-w-md mx-auto text-center space-y-4 p-6">
          <h1 className="text-xl font-black text-[var(--theme-text-primary)] tracking-tight">
            The sample roll didn't load
          </h1>
          <p className="text-sm text-[var(--theme-text-muted)]">
            Nothing was saved. Try again, or head back to the landing page.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              onClick={() => refetch()}
              className="h-12 inline-flex items-center gap-2 rounded-xl px-6 text-sm font-black bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              data-testid="demo-retry"
            >
              Try again
            </button>
            <Link
              to="/"
              className="h-12 inline-flex items-center rounded-xl px-6 text-sm font-bold border border-[var(--theme-border)] text-[var(--theme-text-primary)] transition-colors hover:border-[var(--theme-comic-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
            >
              Back to Comic Pile
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen px-4 py-12 bg-[var(--theme-bg-page)]" data-testid="demo-roll-page">
      <div className="max-w-2xl mx-auto space-y-6">
        <section
          aria-label="Demo notice"
          className="rounded-xl border border-[var(--theme-warning)]/40 bg-[var(--theme-warning)]/10 px-4 py-3 text-sm text-[var(--theme-text-primary)]"
        >
          <p className="font-bold">Sample / Demo data — not saved to any account.</p>
          <p className="text-[var(--theme-text-muted)]">
            This is one deterministic seeded roll. Nothing is written to a library, queue, or reading graph.
          </p>
        </section>

        <section aria-label="Roll result" className="surface-panel p-6 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="inline-flex items-center rounded-full bg-[var(--theme-warning)]/15 text-[var(--theme-warning)] text-xs font-black px-2.5 py-0.5 uppercase tracking-wide">
              Demo
            </span>
            <h1 className="text-xl font-black text-[var(--theme-text-primary)] tracking-tight">{data.title}</h1>
          </div>

          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            <div>
              <dt className="text-xs text-[var(--theme-text-muted)]">Format</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">{data.format}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--theme-text-muted)]">Issues remaining</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">{data.issues_remaining}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--theme-text-muted)]">Die / result</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">d{data.die_size} → {data.result}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--theme-text-muted)]">Reading progress</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">{data.reading_progress ?? '—'}</dd>
            </div>
          </dl>

          <p className="text-sm text-[var(--theme-text-muted)]">{data.explanation}</p>
        </section>

        <section aria-label="Rate this sample" className="surface-panel p-6 space-y-4">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-base font-bold text-[var(--theme-text-primary)]">Rate the sample read</h2>
            <p
              id="demo-rating-value"
              className="text-3xl font-black text-[var(--theme-personal-accent)]"
              data-testid="demo-rating-value"
            >
              {rating.toFixed(1)}
            </p>
          </div>

          <input
            type="range"
            name="demo-rating"
            min={RATING_MIN}
            max={RATING_MAX}
            step={RATING_STEP}
            value={rating}
            className="rating-slider h-4 w-full"
            // SAFETY: the custom property is read by the slider fill gradient, not by React's CSSProperties
            style={{ '--slider-fill': `${ratingFillPct}%` } as CSSProperties}
            aria-label="Sample rating from 0.5 to 5.0 in steps of 0.5"
            aria-describedby="demo-rating-effect"
            data-testid="demo-rating-input"
            onChange={(event) => {
              setRating(Number(event.target.value))
              setRated(true)
            }}
          />

          <p id="demo-rating-effect" className="text-xs text-[var(--theme-text-muted)]">
            {rating >= QUEUE_PROMOTION_THRESHOLD
              ? 'In a real library this rating moves the series to the front of your queue and steps your die down.'
              : 'In a real library this rating slides the series past the next roll and steps your die up.'}
          </p>

          <p aria-live="polite" className="text-sm text-[var(--theme-text-muted)]">
            {rated ? (
              <span className="text-[var(--theme-comic-accent)] font-bold" data-testid="demo-rated">
                {`Rated ${rating.toFixed(1)} — held in this demo session only, never saved.`}
              </span>
            ) : (
              'Move the slider to see how a rating changes tomorrow’s roll.'
            )}
          </p>
        </section>

        <section aria-label="Continue" className="surface-panel p-6 text-center space-y-4">
          <h2 className="text-xl font-black text-[var(--theme-text-primary)] tracking-tight">
            Keep the stack going
          </h2>
          <p className="text-sm text-[var(--theme-text-muted)] max-w-md mx-auto">
            This demo roll is ephemeral — your rating isn’t saved, and no library was created. Sign up or
            log in to build your real queue and start tracking.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link
              to="/register"
              className="h-12 inline-flex items-center gap-2 rounded-xl px-6 text-sm font-black bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              data-testid="demo-signup-cta"
            >
              <UserIcon className="h-4 w-4" aria-hidden="true" /> Create your queue
            </Link>
            <Link
              to="/login"
              className="h-12 inline-flex items-center rounded-xl px-6 text-sm font-bold border border-[var(--theme-border)] text-[var(--theme-text-primary)] transition-colors hover:border-[var(--theme-comic-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
              data-testid="demo-login-cta"
            >
              Sign in
            </Link>
          </div>
        </section>

        <div className="text-center">
          <Link
            to="/"
            className="text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
          >
            ← Back to Comic Pile
          </Link>
        </div>
      </div>
    </div>
  )
}
