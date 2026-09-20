import type { FormEvent } from 'react'
import {
  ContinuityIssueSelector,
  ContinuityThreadSelector,
} from '../../components/continuity'
import type { DependencyGroup } from '../../services/api-dependency-groups'
import type { Issue, Thread } from '../../types'
import type { ContinuityPlannerEditor } from './useContinuityPlannerEditor'

interface PlannerAddStepsProps {
  editor: ContinuityPlannerEditor
  threads: Thread[]
  issues: Issue[]
  issuesLoading: boolean
  issueLoadError: string | null
  groups: DependencyGroup[]
}

/**
 * Presentational "Add steps" section: issue form plus crossover picker.
 * Holds no state; draft selection state and add actions come from the editor.
 */
export default function PlannerAddSteps({
  editor,
  threads,
  issues,
  issuesLoading,
  issueLoadError,
  groups,
}: PlannerAddStepsProps) {
  const lanesEmpty = editor.orderedLanes.length === 0
  const targetLaneName =
    editor.orderedLanes.find((lane) => lane.id === editor.targetLaneId)?.name ??
    editor.orderedLanes[0]?.name ??
    'lane'

  const submitIssue = (event: FormEvent) => {
    event.preventDefault()
    editor.addIssue()
  }

  return (
    <section aria-labelledby="add-steps-heading" className="border-t border-[var(--theme-border)] pt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2
          id="add-steps-heading"
          className="text-xs font-black uppercase tracking-widest text-[var(--theme-text-primary)]"
        >
          Add steps
        </h2>
        <p className="text-xs text-[var(--theme-text-muted)]">
          {lanesEmpty ? 'Add a lane first' : `To ${targetLaneName} · issue or crossover`}
        </p>
      </div>
      <div className="mt-4 grid gap-6 md:grid-cols-2 md:divide-x md:divide-[var(--theme-border)]">
        <form onSubmit={submitIssue} className="space-y-3 md:pr-6" aria-label="Add an issue">
          <h3 className="text-sm font-bold text-[var(--theme-text-primary)]">Issue</h3>
          <ContinuityThreadSelector
            threads={threads}
            value={editor.selectedThread}
            onChange={(thread) => editor.selectThread(thread)}
            label="Comic series"
          />
          <ContinuityIssueSelector
            issues={issues}
            value={editor.selectedIssue}
            onChange={editor.setSelectedIssue}
            isLoading={issuesLoading}
            disabled={!editor.selectedThread || lanesEmpty}
            error={issueLoadError}
          />
          <button
            type="submit"
            disabled={!editor.selectedIssue || lanesEmpty}
            className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-panel)] disabled:opacity-50"
          >
            Add issue
          </button>
          {lanesEmpty && (
            <p className="text-xs text-[var(--theme-text-muted)]">Add a lane first to add issues.</p>
          )}
        </form>

        <div className="space-y-3 border-t border-[var(--theme-border)] pt-6 md:border-t-0 md:pt-0 md:pl-6">
          <h3 className="text-sm font-bold text-[var(--theme-text-primary)]">Crossover</h3>
          <label className="block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
            Crossover
            <select
              value={editor.selectedGroupId}
              onChange={(event) => editor.setSelectedGroupId(event.target.value)}
              className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)]"
              disabled={lanesEmpty}
            >
              <option value="">Select a crossover</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={editor.addCrossover}
            disabled={!editor.selectedGroupId || lanesEmpty}
            className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-panel)] disabled:opacity-50"
          >
            Add crossover
          </button>
          {lanesEmpty && (
            <p className="text-xs text-[var(--theme-text-muted)]">
              Add a lane first to add crossovers.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
