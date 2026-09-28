import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CircleStackIcon,
  CodeBracketIcon,
  Squares2X2Icon,
} from '@heroicons/react/24/outline'
import { isReturningVisitor } from '../utils/returningVisitor'

const FEATURES = [
  {
    icon: Squares2X2Icon,
    title: 'Dice-Driven Discovery',
    description:
      'Let fate decide your next read. Roll the dice and discover unexpected gems from your collection.',
  },
  {
    icon: CircleStackIcon,
    title: 'Smart Tracking',
    description:
      "Keep track of what you've read, what's next, and what's still in your stack. Never lose your place.",
  },
  {
    icon: CodeBracketIcon,
    title: 'Open Source',
    description:
      'Built in the open with an MIT license. Own your data, control your collection, and join the community.',
  },
]

export default function LandingPage() {
  const [isReturning] = useState<boolean>(() => isReturningVisitor())

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12 bg-[var(--theme-bg-page)]">
      <div className="w-full max-w-4xl space-y-8">
        {/* Hero Section */}
        <div className="text-center space-y-2">
          <p className="text-[10px] font-black uppercase tracking-[0.28em] text-[var(--theme-primary-action)]">Comic Pile · Roll to read. Rotate your stack.</p>
          <h1 className="text-4xl font-black tracking-tighter text-glow uppercase">
            Your Comic Collection, <span className="text-[var(--theme-primary-action)]">Roll by Roll</span>
          </h1>
          <p className="text-sm text-[var(--theme-text-muted)] max-w-2xl mx-auto">
            An open-source, dice-driven comic reading tracker. Discover new issues, track your progress, and never lose your place in the stack.
          </p>
        </div>

        {/* Features Section */}
        <div className="grid gap-4 md:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, description }) => (
            <div key={title} className="bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl p-6 space-y-3">
              <Icon className="h-6 w-6 text-[var(--theme-primary-action)]" aria-hidden="true" />
              <h2 className="text-base font-bold text-[var(--theme-text-primary)]">{title}</h2>
              <p className="text-sm text-[var(--theme-text-muted)]">{description}</p>
            </div>
          ))}
        </div>

        {/* CTA Section */}
        <div className="text-center space-y-4">
          <Link
            to="/register"
            className="w-full md:w-auto h-12 bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] rounded-xl text-sm font-bold text-stone-900 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] px-8 inline-block"
          >
            Sign Up Free
          </Link>
          <p className="text-xs text-[var(--theme-text-muted)]">
            No credit card required. Start tracking your comics in 60 seconds.
          </p>
          <p className="text-sm text-[var(--theme-text-muted)]">
            {isReturning ? 'Welcome back' : 'Already have an account?'}{' '}
            <Link
              to="/login"
              className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity"
            >
              Sign in
            </Link>
          </p>
        </div>

        {/* Footer */}
        <div className="text-center space-y-3 pt-6 border-t border-[var(--theme-border)]">
          <p className="text-xs text-[var(--theme-text-muted)]">
            Comic Pile is MIT-licensed and built in public.{' '}
            <a
              href="https://github.com/JoshCLWren/comic-pile"
              target="_blank"
              rel="noreferrer"
              className="text-[var(--theme-primary-action)] hover:opacity-80 font-bold transition-opacity"
            >
              View the source on GitHub
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}
