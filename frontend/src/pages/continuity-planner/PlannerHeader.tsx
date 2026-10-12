import GlossaryLink from '../../components/GlossaryLink'
import { displayCblSourcePath } from '../../utils/cblSourceDisplay'
import type { ContinuityPlannerEditor } from './useContinuityPlannerEditor'

interface PlannerHeaderProps {
  editor: ContinuityPlannerEditor
  planId: number | null
  onReopenLast: (planId: string) => void
}

/**
 * Presentational planner shell header: title, CBL source banner,
 * reopen-last affordance, plan name, and ordering-mode controls.
 * Holds no state; all behavior comes from the editor hook.
 */
export default function PlannerHeader({ editor, planId, onReopenLast }: PlannerHeaderProps) {
  return (
    <>
      <header>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h1 id="planner-heading" className="text-2xl font-black text-[var(--theme-text-primary)]">
              {planId ? `Edit ${editor.name || 'Reading Plan'}` : 'New Reading Plan'}
            </h1>
            <p className="mt-2 text-sm text-[var(--theme-text-muted)]">
              Arrange issues in source reading order or your own order. Strict records intent for
              selected hard prerequisites; compiling them from plan order is not active yet. Source
              reading order is not a blocker by itself.{' '}
              <GlossaryLink id="reading-plan">Reading Plan</GlossaryLink>,{' '}
              <GlossaryLink id="lane">Lane</GlossaryLink>, and{' '}
              <GlossaryLink id="crossover">Crossover</GlossaryLink> definitions.
            </p>
          </div>
          {planId && (
            <button
              type="button"
              onClick={() => onReopenLast(String(planId))}
              className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
            >
              View plan
            </button>
          )}
        </div>
      </header>

      {editor.sourcePaths.length > 0 && (
        <section
          className="rounded-xl border border-[var(--theme-continuity-accent)] bg-[var(--theme-bg-panel)] p-4"
          aria-labelledby="plan-sources-heading"
        >
          <div className="flex flex-wrap items-baseline gap-2">
            <h2
              id="plan-sources-heading"
              className="text-sm font-black text-[var(--theme-continuity-accent)]"
            >
              Source reading order
            </h2>
            <p className="text-xs font-black text-[var(--theme-continuity-accent)]">CBL-backed</p>
            <p className="text-xs text-[var(--theme-text-muted)]">
              This Reading Plan uses the following source reading order.
            </p>
          </div>
          <ul className="mt-2 space-y-1 text-xs text-[var(--theme-text-primary)]">
            {editor.sourcePaths.map((path) => {
              const displayed = displayCblSourcePath(path)
              return displayed ? <li key={path}>Source: {displayed}</li> : null
            })}
          </ul>
        </section>
      )}

      {!planId && editor.lastPlanId && (
        <button
          type="button"
          onClick={() => editor.lastPlanId && onReopenLast(editor.lastPlanId)}
          className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]"
        >
          Reopen last saved plan
        </button>
      )}

      <label className="block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
        Plan name
        <input
          value={editor.name}
          onChange={(event) => editor.setName(event.target.value)}
          maxLength={200}
          className="mt-1 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-3 text-[var(--theme-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)]"
        />
      </label>

      <fieldset className="block" aria-describedby="ordering-mode-help">
        <legend className="text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
          Ordering mode
        </legend>
        <p id="ordering-mode-help" className="mt-1 text-sm text-[var(--theme-text-muted)]">
          Informational plans keep source reading order as a reference and add no hard blockers.
          Strict records that intent; selected hard prerequisites are not compiled from plan order
          yet.{' '}
          <GlossaryLink id="ordering-mode">What is an ordering mode?</GlossaryLink>
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-xl border bg-[var(--theme-bg-panel)] p-3 ${
              editor.orderingMode === 'informational'
                ? 'border-[var(--theme-continuity-accent)]'
                : 'border-[var(--theme-border)]'
            }`}
          >
            <input
              type="radio"
              name="ordering-mode"
              value="informational"
              checked={editor.orderingMode === 'informational'}
              onChange={() => editor.setOrderingMode('informational')}
              className="mt-0.5 accent-[var(--theme-continuity-accent)]"
            />
            <span className="text-sm">
              <span className="font-bold text-[var(--theme-text-primary)]">Informational</span>
              <span className="ml-1.5 text-xs text-[var(--theme-text-dim)]">
                Suggested order — never blocks reading.
              </span>
            </span>
          </label>
          <label
            className={`flex cursor-pointer items-start gap-3 rounded-xl border bg-[var(--theme-bg-panel)] p-3 ${
              editor.orderingMode === 'strict_sequential'
                ? 'border-[var(--theme-continuity-accent)]'
                : 'border-[var(--theme-border)]'
            } ${editor.lanes.length > 1 ? 'pointer-events-none opacity-50' : ''}`}
          >
            <input
              type="radio"
              name="ordering-mode"
              value="strict_sequential"
              checked={editor.orderingMode === 'strict_sequential'}
              onChange={() => editor.setOrderingMode('strict_sequential')}
              disabled={editor.lanes.length > 1}
              className="mt-0.5 accent-[var(--theme-continuity-accent)]"
            />
            <span className="text-sm">
              <span className="font-bold text-[var(--theme-text-primary)]">Strict</span>
              <span className="ml-1.5 text-xs text-[var(--theme-text-dim)]">
                Records intent — plan-order blockers are not compiled yet.
              </span>
            </span>
          </label>
        </div>
        {editor.lanes.length > 1 && (
          <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
            Strict requires exactly one lane.
          </p>
        )}
      </fieldset>
    </>
  )
}
