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
          <h1 id="hero-heading" className="text-4xl font-black tracking-tighter text-[var(--theme-text-primary)]">
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
                Add each series you want to read. Set the format (single issues, trades, omnibuses),
                how many issues remain, and any notes. Threads sit in your queue until rolled.
              </p>
            </article>
            <article className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-3">
              <QueueListIcon className="h-8 w-8 text-[var(--theme-continuity-accent)]" aria-hidden="true" />
              <h3 className="text-base font-bold text-[var(--theme-text-primary)]">2. Roll for your next read</h3>
              <p className="text-sm text-[var(--theme-text-muted)] leading-relaxed">
                Hit Roll. Comic Pile weights your queue by issues remaining, your personal ratings,
                continuity dependencies, and active sessions — then picks one. No algorithmic feed;
                just your stack, shuffled with intent.
              </p>
            </article>
            <article className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-3">
              <ChartBarIcon className="h-8 w-8 text-[var(--theme-personal-accent)]" aria-hidden="true" />
              <h3 className="text-base font-bold text-[var(--theme-text-primary)]">3. Read, rate, repeat</h3>
              <p className="text-sm text-[var(--theme-text-muted)] leading-relaxed">
                The rolled thread opens to your current issue. Read, then rate 0.5–5.0. Ratings
                feed back into future rolls. Progress, continuity links, and session history all
                persist — your place is never lost.
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
                Higher-rated threads roll more often. Actively reading a crossover? Its threads
                surface first. The queue learns from what you actually enjoy.
              </dd>
            </div>
            <div className="space-y-1">
              <dt className="text-sm font-bold text-[var(--theme-text-primary)]">Continuity-aware</dt>
              <dd className="text-sm text-[var(--theme-text-muted)]">
                Link crossover events and reading orders. When you roll a tie-in, its main event
                and sibling threads get a boost — so you read in the order the story demands.
              </dd>
            </div>
            <div className="space-y-1">
              <dt className="text-sm font-bold text-[var(--theme-text-primary)]">No external dependencies</dt>
              <dd className="text-sm text-[var(--theme-text-muted)]">
                Self-hosted, MIT-licensed, PostgreSQL-backed. Your collection lives on your
                hardware. No cloud sync, no accounts on our servers, no feature gating.
              </dd>
            </div>
            <div className="space-y-1">
              <dt className="text-sm font-bold text-[var(--theme-text-primary)]">Built for the long stack</dt>
              <dd className="text-sm text-[var(--theme-text-muted)]">
                Hundreds of threads, multi-year runs, omnibuses split across formats — the
                data model handles real collections, not happy-path demos.
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
            {isReturning ? 'Welcome back' : 'New here?'}{' '}
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