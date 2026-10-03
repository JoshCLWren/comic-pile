import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CubeIcon, UserIcon } from '@heroicons/react/24/outline'
import { useQuery } from '@tanstack/react-query'

export default function DemoRollPage() {
  const [rating, setRating] = useState<number | null>(null)
  const [rated, setRated] = useState(false)

  const { data, isPending } = useQuery({
    queryKey: ['demo', 'roll'],
    queryFn: async () => {
      const res = await fetch('/api/demo/roll')
      if (!res.ok) throw new Error('Demo roll failed')
      return res.json() as Promise<{
        thread_id: number
        title: string
        format: string
        issues_remaining: number
        die_size: number
        result: number
        reading_progress: string | null
        explanation: string | null
      }>
    },
  })

  const handleRate = (value: number) => {
    setRating(value)
    setRated(true)
  }

  if (isPending) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]" data-demo-roll-loading>
        <div className="text-center space-y-3">
          <CubeIcon className="h-10 w-10 mx-auto animate-spin text-[var(--theme-comic-accent)]" aria-hidden="true" />
          <p className="text-sm font-bold text-[var(--theme-text-muted)]">Seeding sample roll…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen px-4 py-12 bg-[var(--theme-bg-page)]" data-demo-roll-page>
      <div className="max-w-2xl mx-auto space-y-8">
        {/* Sample banner */}
        <section aria-label="Demo notice" className="rounded-xl border border-amber-300/40 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-900 dark:text-amber-100">
          <p className="font-bold">Sample / Demo data — not saved to any account.</p>
          <p className="opacity-90">This is one deterministic seeded roll. Nothing is written to a library, queue, or graph.</p>
        </section>

        {/* Roll result */}
        <section aria-label="Roll result" className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-2xl p-6 space-y-4 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-100 text-xs font-black px-2.5 py-0.5 uppercase tracking-wide">Demo</span>
            <h1 className="text-xl font-black text-[var(--theme-text-primary)] tracking-tight">{data?.title}</h1>
          </div>

          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
            <div>
              <dt className="text-[var(--theme-text-muted)]">Format</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">{data?.format}</dd>
            </div>
            <div>
              <dt className="text-[var(--theme-text-muted)]">Issues remaining</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">{data?.issues_remaining}</dd>
            </div>
            <div>
              <dt className="text-[var(--theme-text-muted)]">Die size / result</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">{data?.die_size} / {data?.result}</dd>
            </div>
            <div>
              <dt className="text-[var(--theme-text-muted)]">Reading progress</dt>
              <dd className="font-bold text-[var(--theme-text-primary)]">{data?.reading_progress ?? '—'}</dd>
            </div>
          </dl>

          <p className="text-sm text-[var(--theme-text-muted)]">{data?.explanation}</p>
        </section>

        {/* Rating loop (ephemeral) */}
        <section aria-label="Rate this sample" className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-2xl p-6 space-y-4 shadow-sm">
          <h2 className="text-base font-bold text-[var(--theme-text-primary)]">Rate the sample read</h2>
          <div className="flex gap-2 flex-wrap" role="radiogroup" aria-label="Rating">
            {[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0].map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => handleRate(v)}
                aria-checked={rating === v}
                role="radio"
                className={`h-10 w-10 rounded-xl font-black text-sm transition-colors border focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] ${
                  rating === v
                    ? 'bg-[var(--theme-primary-action)] text-stone-900 border-transparent'
                    : 'bg-[var(--theme-bg-card)] text-[var(--theme-text-primary)] border-[var(--theme-border)] hover:border-[var(--theme-comic-accent)]'
                }`}
              >
                {v}
              </button>
            ))}
          </div>
          {rated && (
            <p className="text-sm text-[var(--theme-comic-accent)] font-bold" data-demo-rated>Rated {rating} — this is only for this demo session.</p>
          )}
        </section>

        {/* Conversion CTA */}
        <section aria-label="Continue" className="rounded-2xl bg-gradient-to-br from-[var(--theme-primary-action)] to-[var(--theme-comic-accent)] px-8 py-10 text-center space-y-4 shadow-lg">
          <h2 className="text-2xl font-black text-stone-900 tracking-tight">Keep the stack going</h2>
          <p className="text-sm font-medium text-stone-900/90 max-w-md mx-auto">
            The demo roll is ephemeral — your rating isn't saved, and no library was created. Sign up or log in to build your real queue and start tracking.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link
              to="/register"
              className="inline-flex items-center gap-2 h-12 bg-stone-900 text-white rounded-xl text-sm font-black px-6 hover:bg-stone-800 transition-colors focus:outline-none focus:ring-2 focus:ring-white/60"
              data-demo-signup-cta
            >
              <UserIcon className="h-4 w-4" aria-hidden="true" /> Create your queue
            </Link>
            <Link
              to="/login"
              className="inline-flex items-center gap-2 h-12 bg-white/20 text-stone-900 rounded-xl text-sm font-black px-6 hover:bg-white/30 transition-colors focus:outline-none focus:ring-2 focus:ring-white/60 border border-stone-900/10"
              data-demo-login-cta
            >
              Sign in
            </Link>
          </div>
        </section>

        {/* Back to landing */}
        <div className="text-center">
          <Link to="/" className="text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors">← Back to Comic Pile</Link>
        </div>
      </div>
    </div>
  )
}
