import React, { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

// Simple, static glossary help page for core app concepts.
// This is intentionally content-forward and does not touch backend.

type Term = {
  id: string
  term: string
  def: string
}

const DEFINITIONS: Term[] = [
  {
    id: 'thread',
    term: 'Series',
    def: 'One comic series you are tracking, read issue by issue.',
  },
  {
    id: 'ready-to-read',
    term: 'Ready to read',
    def: 'Series that can be picked for your next roll right now, because nothing earlier in their reading order is waiting. The Roll page counts these as "N ready to read".',
  },
  {
    id: 'roll-pool',
    term: 'Roll pool',
    def: 'The ready-to-read series a roll picks from.',
  },
  {
    id: 'ladder-mode',
    term: 'Auto-adjust',
    def: 'Lets the die pick its own size to match how many series are ready to read. The "Auto" control on Roll turns it back on after you choose a die size by hand.',
  },
  {
    id: 'die-ladder',
    term: 'Die size',
    def: 'Sets how many series the roll can pick from. Sizes run d4 → d6 → d8 → d10 → d12 → d20 → d30 → d50 → d100, and a larger die includes more of your ready-to-read series. A readout like "d6 → d8" shows the step your die moves after a rating.',
  },
  {
    id: 'autoladder',
    term: 'Auto',
    def: 'Keeps the die size matched to your ready-to-read series. The "Auto" control on Roll turns this back on after you choose a die size by hand.',
  },
  {
    id: 'offset',
    term: 'Offset',
    def: 'Shifts your roll result up or down (e.g. +1 means result+1 is selected).',
  },
  {
    id: 'snoozed',
    term: 'Snoozed',
    def: 'Temporarily excluded from rolling — won’t appear in the roll pool.',
  },
  {
    id: 'position',
    term: 'Pos',
    def: 'Queue-order shortcut. "Pos" sorts your series from first to last in the reading queue.',
  },
  {
    id: 'reading-mode',
    term: 'Reading mode',
    def: 'How Comic Pile shapes the roll for your mood. Bandwidth sets how demanding comics feel right now (Light, Balanced, Deep); intent sets what kind of pick sounds good (Balanced, Momentum, Familiar, Explore, Random).',
  },
  {
    id: 'finished-series',
    term: 'Finished series',
    def: 'A series you have read to the end. Finished series stay out of the queue until you add new issues — use the "Add back to queue" action to bring one back.',
  },
  {
    id: 'dependency',
    term: 'Dependency rule',
    def: 'A reading order rule: "read X before Y". Create or manage them via the Dependency Builder (open from a series\'s Queue card or from the dependency dialog inside an issue list). Deleting a single rule does not require editing an entire plan.',
  },
  {
    id: 'readiness',
    term: 'Blocked',
    def: 'A comic with an unsatisfied hard prerequisite stays out of the roll pool until that prerequisite is read. Roll is the authority for what can be selected; the product does not ask a second subsystem whether the selected item is ready.',
  },
  {
    id: 'crossover',
    term: 'Crossover',
    def: 'A named group of comics or issues that share one story. Membership labels the group so its continuity is easy to recognize across ComicPile — it does not create a reading block by itself.',
  },
  {
    id: 'continuity-plan',
    term: 'Continuity Plan',
    def: 'A saved arrangement of issues, series, and crossovers in one or more reading lanes. Saving creates only the continuity rules you chose — informational plans create none, strict sequential plans create one per step (see Ordering mode).',
  },
  {
    id: 'ordering-mode',
    term: 'Ordering mode',
    def: 'What saving a plan commits to. Informational plans create no blocking rules and cannot block anything. Strict sequential plans require you to read each step before the next, compiling one blocking rule per step just like the Dependency Builder. Plan ordering never mixes with the Queue\'s issue-level Dependency Builder unless you choose strict sequential.',
  },
  {
    id: 'lane',
    term: 'Lane',
    def: 'One ordered column of steps inside a continuity plan. Multiple lanes let parallel storylines read side by side.',
  },
  {
    id: 'reading-order',
    term: 'Reading Order',
    def: 'The saved sequence used to pick what you read. Issues join it as soon as everything before them has been read.',
  },
  {
    id: 'projection',
    term: 'Projection',
    def: 'Applying a continuity plan to a saved reading order. You preview the result first and confirm before it is applied — your plan is never modified.',
  },
  {
    id: 'dependency-builder',
    term: 'Dependency Builder',
    def: 'The editable surface for creating, viewing, and removing issue-level dependency rules. Access it from any Queue card (Dependencies in the series actions menu) or from the dependency dialog inside an issue list.',
  },
]

/**
 * Scrolls the glossary to a definition when the page is opened through a
 * cross-link such as `/glossary#crossover`. Defers two animation frames so it
 * runs after the app's route-level scroll restoration.
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
      const target = document.getElementById(id)
      if (target) target.scrollIntoView({ block: 'start', behavior: 'auto' })
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

export default function HelpPage() {
  useGlossaryAnchorScroll()
  return (
    <section aria-label="Help and glossary" className="pt-4 pb-12 w-full" data-testid="glossary-list">
      <h1 className="text-2xl font-bold mb-4">Glossary</h1>
      <p className="text-sm text-stone-600 mb-6">Definitions for every reader-facing concept in ComicPile. 1–2 sentence explanations, mobile-friendly layout.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {DEFINITIONS.map((d) => (
          <div key={d.id} id={d.id} className="p-4 border rounded-lg bg-white/80 shadow-sm">
            <div className="text-sm font-semibold uppercase tracking-widest text-stone-600 mb-2" data-testid="glossary-term">{d.term}</div>
            <div className="text-sm text-stone-700" data-testid="glossary-definition">{d.def}</div>
          </div>
        ))}
      </div>
    </section>
  )
}