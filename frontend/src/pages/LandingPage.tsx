import { Link } from 'react-router-dom'
import { isReturningVisitor } from '../utils/returningVisitor'

export default function LandingPage() {
  const isReturning = isReturningVisitor()

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
      <div className="w-full max-w-4xl space-y-12">
        {/* Hero Section */}
        <div className="text-center space-y-6">
          <div className="space-y-2">
            <p className="text-[10px] font-black uppercase tracking-[0.28em] text-[var(--theme-primary-action)]">Comic Pile · Roll to read. Rotate your stack.</p>
            <h1 className="text-5xl md:text-6xl font-black tracking-tighter text-glow uppercase">
              Your Comic Collection, 
              <br />
              <span className="text-[var(--theme-primary-action)]">Roll by Roll</span>
            </h1>
            <p className="text-lg md:text-xl text-[var(--theme-text-muted)] max-w-2xl mx-auto">
              An open-source, dice-driven comic reading tracker. Discover new issues, track your progress, and never lose your place in the stack.
            </p>
          </div>
        </div>

        {/* Features Section */}
        <div className="grid md:grid-cols-3 gap-8">
          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-4">
            <div className="w-12 h-12 bg-[var(--theme-primary-action)]/10 rounded-xl flex items-center justify-center">
              <div className="w-6 h-6 bg-[var(--theme-primary-action)] rounded" />
            </div>
            <h3 className="text-lg font-bold text-[var(--theme-text-primary)]">Dice-Driven Discovery</h3>
            <p className="text-sm text-[var(--theme-text-muted)]">
              Let fate decide your next read. Roll the dice and discover unexpected gems from your collection.
            </p>
          </div>

          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-4">
            <div className="w-12 h-12 bg-[var(--theme-primary-action)]/10 rounded-xl flex items-center justify-center">
              <div className="w-6 h-6 bg-[var(--theme-primary-action)] rounded" />
            </div>
            <h3 className="text-lg font-bold text-[var(--theme-text-primary)]">Smart Tracking</h3>
            <p className="text-sm text-[var(--theme-text-muted)]">
              Keep track of what you've read, what's next, and what's still in your stack. Never lose your place.
            </p>
          </div>

          <div className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-4">
            <div className="w-12 h-12 bg-[var(--theme-primary-action)]/10 rounded-xl flex items-center justify-center">
              <div className="w-6 h-6 bg-[var(--theme-primary-action)] rounded" />
            </div>
            <h3 className="text-lg font-bold text-[var(--theme-text-primary)]">Open Source</h3>
            <p className="text-sm text-[var(--theme-text-muted)]">
              Built in the open with MIT license. Own your data, control your collection, and join the community.
            </p>
          </div>
        </div>

        {/* CTA Section */}
        <div className="text-center space-y-6">
          <div className="space-y-4">
            <Link 
              to="/register" 
              className="w-full md:w-auto h-14 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-[11px] font-black uppercase tracking-widest text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] px-8 inline-block"
            >
              Sign Up Free
            </Link>
            <p className="text-sm text-[var(--theme-text-muted)]">
              No credit card required. Start tracking your comics in 60 seconds.
            </p>
          </div>

          {isReturning && (
            <div className="space-y-2">
              <p className="text-sm text-[var(--theme-text-muted)]">
                Already have an account?
              </p>
              <Link 
                to="/login" 
                className="inline-block h-12 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] hover:border-[var(--theme-primary-action)] rounded-xl text-[11px] font-bold uppercase tracking-widest text-[var(--theme-primary-action)] transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] px-6"
              >
                Sign In
              </Link>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="text-center space-y-4 pt-8 border-t border-[var(--theme-border)]">
          <p className="text-xs text-[var(--theme-text-muted)]">
            Comic Pile is MIT-licensed and built in public.
          </p>
          <a
            href="https://github.com/JoshCLWren/comic-pile"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity inline-block"
          >
            View the source on GitHub
          </a>
        </div>
      </div>
    </div>
  )
}
