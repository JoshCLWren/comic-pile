import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CubeIcon, QueueListIcon, ChartBarIcon } from '@heroicons/react/24/outline'
import { isReturningVisitor } from '../utils/returningVisitor'

export default function LandingPage() {
  const [isReturning] = useState<boolean>(() => isReturningVisitor())

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
      <div className="w-full max-w-4xl space-y-10">
        {/* Hero Section - concrete product concept */}
        <section className="text-center space-y-4" aria-labelledby="hero-heading">
          <p className="text-[10px] font-black uppercase tracking-[0.28em] text-[var(--theme-comic-accent)]">
            Comic Pile · Roll to read. Rotate your stack.
          </p>
          <h1 id="hero-heading" className="text-4xl font-black tracking-tighter text-glow text-[var(--theme-text-primary)]">
            A dice-driven reading queue for your comic collection.
          </h1>
          <p className="text-base text-[var(--theme-text-muted)] max-w-2xl mx-auto leading-relaxed">
            Add your series, set how many issues remain, and roll. Comic Pile picks the next thread
            from your queue — respecting what you're actively reading, your continuity plans, and
            the series you've rated highest. Choice paralysis solved; your stack stays yours.
          </p>
        </section>

        {/* How it works - explains the roll mechanic concretely */}
        <section className="space-y-6" aria-labelledby="how-heading">
          <h2 id="how-heading" className="text-xl font-bold text-[var(--theme-text-primary)] text-center">
            How the roll works
          </h2>
          <div className="grid gap-4 md:grid-cols-3">
            <article className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-3">
              <CubeIcon className="h-8 w-8 text-[var(--theme-comic-accent)]" aria-hidden="true" />
              <h3 className="text-base font-bold text-[var(--theme-text-primary)]">1. Build your queue</h3>
              <p className="text-sm text-[var(--theme-text-muted)] leading-relaxed">
                Add each series you want to read and pick its format — comic, manga, trade
                paperback, graphic novel, digital, or your own. Set how many issues remain and
                leave yourself notes. Every thread keeps its own position, ratings, and progress.
              </p>
            </article>
            <article className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-3">
              <QueueListIcon className="h-8 w-8 text-[var(--theme-continuity-accent)]" aria-hidden="true" />
              <h3 className="text-base font-bold text-[var(--theme-text-primary)]">2. Roll for your next read</h3>
              <p className="text-sm text-[var(--theme-text-muted)] leading-relaxed">
                Hit Roll and the die draws from the top of your queue — the die size is the pool,
                so a smaller die means fewer, more deliberate picks. Rating a series 4.0 or higher
                moves it to the front of the queue and steps the die down; rating it lower slides
                it past the next roll and steps the die up. Ask for a light issue or a deep one and
                the draw is biased to match.
              </p>
            </article>
            <article className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-3">
              <ChartBarIcon className="h-8 w-8 text-[var(--theme-personal-accent)]" aria-hidden="true" />
              <h3 className="text-base font-bold text-[var(--theme-text-primary)]">3. Read, rate, repeat</h3>
              <p className="text-sm text-[var(--theme-text-muted)] leading-relaxed">
                The roll lands on a thread with its reading progress and the next issue already
                loaded. Read it, then rate it 0.5–5.0. Your rating changes where the thread sits
                tomorrow, and every session, rating, and continuity link stays stored — your place
                is never lost.
              </p>
            </article>
          </div>
        </section>

        {/* What makes it different - concrete differentiators */}
        <section className="space-y-6 border-t border-[var(--theme-border)] pt-8" aria-labelledby="why-heading">
          <h2 id="why-heading" className="text-xl font-bold text-[var(--theme-text-primary)] text-center">
            Why it's not just a tracker
          </h2>
          <dl className="grid gap-4 md:grid-cols-2 max-w-3xl mx-auto">
            <div className="space-y-1">
              <dt className="text-sm font-bold text-[var(--theme-text-primary)]">Weighted by your history</dt>
              <dd className="text-sm text-[var(--theme-text-muted)]">
                A thread you rated 4.0 or higher climbs to the front of the queue and shrinks your
                die, so the good stuff comes around more often. Rate it lower and it moves past the
                next roll. No popularity feed, no trending list — just what you already rated.
              </dd>
            </div>
            <div className="space-y-1">
              <dt className="text-sm font-bold text-[var(--theme-text-primary)]">Continuity-aware</dt>
              <dd className="text-sm text-[var(--theme-text-muted)]">
                Mark the issue a thread depends on, or link a crossover event and its reading order.
                Until you have read what comes first, the dependent thread is held out of the pool
                entirely — story order beats the dice.
              </dd>
            </div>
            <div className="space-y-1">
              <dt className="text-sm font-bold text-[var(--theme-text-primary)]">No external dependencies</dt>
              <dd className="text-sm text-[var(--theme-text-muted)]">
                Self-hosted, MIT-licensed, PostgreSQL-backed. Your collection lives on your own
                hardware, with no cloud sync and no account on someone else's server.
              </dd>
            </div>
            <div className="space-y-1">
              <dt className="text-sm font-bold text-[var(--theme-text-primary)]">Built for the long stack</dt>
              <dd className="text-sm text-[var(--theme-text-muted)]">
                Big collections and multi-year runs are the normal case, not the demo case. Queue
                position, issues remaining, per-issue progress, dependencies, and session history
                are all tracked per thread.
              </dd>
            </div>
          </dl>
        </section>

        {/* CTA Section */}
        <section className="text-center space-y-4 border-t border-[var(--theme-border)] pt-8" aria-labelledby="cta-heading">
          <h2 id="cta-heading" className="sr-only">Get started</h2>
          <Link
            to="/register"
            className="w-full md:w-auto h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-[10px] font-black uppercase tracking-widest text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] px-8 inline-block"
          >
            Create your queue
          </Link>
          <p className="text-sm text-[var(--theme-text-muted)]">
            {isReturning ? 'Welcome back' : 'Already have an account?'}{' '}
            <Link
              to="/login"
              className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity"
            >
              Sign in
            </Link>
          </p>
        </section>

        {/* Footer - single open-source mention */}
        <footer className="text-center space-y-2 pt-6 border-t border-[var(--theme-border)]" role="contentinfo">
          <p className="text-xs text-[var(--theme-text-muted)]">
            MIT-licensed · <a href="https://github.com/JoshCLWren/comic-pile" target="_blank" rel="noreferrer" className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity">Source on GitHub</a>
          </p>
        </footer>
      </div>
    </div>
  )
}
