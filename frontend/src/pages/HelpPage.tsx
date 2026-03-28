import React from 'react'

// Simple, static glossary help page for core app concepts.
// This is intentionally content-forward and does not touch backend.

type Term = {
  term: string
  def: string
}

const DEFINITIONS: Term[] = [
  {
    term: 'Thread',
    def: 'A comic series you are tracking, read issue by issue.'
  },
  {
    term: 'Roll pool',
    def: 'The threads eligible to be randomly selected for a roll right now.'
  },
  {
    term: 'Ladder mode',
    def: 'Automatically adjusts the die size to match your eligible pool size.'
  },
  {
    term: 'Offset',
    def: 'Shifts your roll result up or down (e.g. +1 means result+1 is selected).'
  },
  {
    term: 'Snoozed',
    def: 'Temporarily excluded from rolling — won’t appear in the roll pool.'
  },
  {
    term: 'Dependencies',
    def: 'Reading order rules: "read X before Y".'
  },
  {
    term: 'Collections',
    def: 'Groups of threads (e.g. "Marvel", "DC", "Currently Reading").'
  }
]

export default function HelpPage() {
  return (
    <section aria-label="Help and glossary" className="pt-4 pb-12 w-full" data-testid="glossary-list">
      <h1 className="text-2xl font-bold mb-4">Help / Glossary</h1>
        <a href="/glossary" className="text-blue-600 hover:underline mb-4 block">Glossary</a>
      <p className="text-sm text-stone-600 mb-6">Definitions for core concepts used in Comic Pile. 1–2 sentence explanations, mobile-friendly layout.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {DEFINITIONS.map((d) => (
          <div key={d.term} className="p-4 border rounded-lg bg-white/80 shadow-sm">
            <div className="text-sm font-semibold uppercase tracking-widest text-stone-600 mb-2" data-testid="glossary-term">{d.term}</div>
            <div className="text-sm text-stone-700" data-testid="glossary-definition">{d.def}</div>
          </div>
        ))}
      </div>
    </section>
  )
}
