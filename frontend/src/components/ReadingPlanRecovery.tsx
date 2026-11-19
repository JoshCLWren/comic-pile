import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  type RecoveryCandidate,
  type RecoveryStep,
} from '../services/api-reading-plan-recovery'
import { useReadingPlanRecoveryPreview, useRelinkReadingPlan } from '../hooks/useReadingPlans'
import CompactIssueCardTrigger from './CompactIssueCardTrigger'
import { useIssueCards, indexIssueCards } from '../hooks/useIssueCards'
import type { IssueCard } from '../services/issueCardsApi'

function StepNames({ steps, cardsByIssue }: { steps: RecoveryStep[]; cardsByIssue: Map<number, IssueCard> }) {
  return (
    <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-[var(--theme-text-muted)]">
      {steps.map((step) => {
        // Labels arrive as "Series #number"; split for a truthful identity hint
        // instead of a bare "?" issue number.
        const match = /^(?<title>.+) #(?<number>[^#]+)$/.exec(step.label)
        const title = match?.groups?.title ?? step.label
        const number = match?.groups?.number ?? '?'
        return (
          <li key={step.issue_id} className="flex flex-wrap items-center gap-2">
            <span className="min-w-0">{step.label} <span className="text-xs">(issue ID {step.issue_id})</span></span>
            <CompactIssueCardTrigger
              issueId={step.issue_id}
              threadTitle={title}
              issueNumber={number}
              card={cardsByIssue.get(step.issue_id) ?? null}
              hideTitle
            />
          </li>
        )
      })}
    </ul>
  )
}

function CandidateChanges({
  candidate,
  cardsByIssue,
  showFullOrder,
  onToggleFullOrder,
}: {
  candidate: RecoveryCandidate
  cardsByIssue: Map<number, IssueCard>
  showFullOrder: boolean
  onToggleFullOrder: (open: boolean) => void
}) {
  return (
    <div className="mt-3 space-y-3 text-sm" data-testid="plan-recovery-diff">
      <p className="font-semibold text-[var(--theme-text-primary)]">
        Preview: {candidate.steps.length} entries, {candidate.mode} mode
      </p>
      {candidate.added_steps.length > 0 && (
        <div>
          <p>Newly authoritative issues ({candidate.added_steps.length}):</p>
          <StepNames steps={candidate.added_steps} cardsByIssue={cardsByIssue} />
        </div>
      )}
      {candidate.removed_steps.length > 0 && (
        <div>
          <p>Saved Plan issues absent from this list ({candidate.removed_steps.length}):</p>
          <StepNames steps={candidate.removed_steps} cardsByIssue={cardsByIssue} />
        </div>
      )}
      {candidate.order_changed && (
        <p className="font-semibold text-[var(--theme-warning)]">
          This selection changes the relative reading order of existing issues.
        </p>
      )}
      {candidate.added_steps.length === 0 &&
        candidate.removed_steps.length === 0 &&
        !candidate.order_changed && (
          <p>The saved membership and order match this Reading List.</p>
        )}
      <details
        open={showFullOrder}
        onToggle={(event) => onToggleFullOrder(event.currentTarget.open)}
      >
        <summary className="cursor-pointer font-semibold">View the complete proposed reading order</summary>
        <StepNames steps={candidate.steps} cardsByIssue={cardsByIssue} />
      </details>
    </div>
  )
}

/**
 * Plan A's original list primary key was deleted. Recovery never infers authority
 * from a matching title or copies old Plan steps into a new Reading List.
 */
export function ReadingPlanRecovery({
  planId,
  onRecovered,
}: {
  planId: number
  onRecovered: () => void
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [showSavedRefs, setShowSavedRefs] = useState(false)
  const [showFullOrder, setShowFullOrder] = useState(false)
  const recovery = useReadingPlanRecoveryPreview(planId)
  const apply = useRelinkReadingPlan(planId, onRecovered)

  // One bounded batch for the sections the reader can actually see: the saved
  // references only when that disclosure is open, and the chosen candidate's
  // diff (plus its full order only when expanded). The server returns every
  // owned list as a candidate, so batching all of them would fetch metadata
  // for the whole collection just to open recovery. Hooks run before early
  // returns so hook order stays stable.
  const previewForCards = recovery.data
  const stepIssueIds = useMemo(
    () => {
      if (!previewForCards) return []
      const ids = new Set<number>()
      if (showSavedRefs) {
        for (const step of previewForCards.retained_steps) ids.add(step.issue_id)
      }
      const selectedCandidate = previewForCards.candidates.find(
        (candidate) => candidate.list_id === selectedId,
      )
      if (selectedCandidate) {
        for (const step of selectedCandidate.added_steps) ids.add(step.issue_id)
        for (const step of selectedCandidate.removed_steps) ids.add(step.issue_id)
        if (showFullOrder) {
          for (const step of selectedCandidate.steps) ids.add(step.issue_id)
        }
      }
      return [...ids]
    },
    [previewForCards, selectedId, showSavedRefs, showFullOrder],
  )
  const cardsQuery = useIssueCards(stepIssueIds, { enabled: stepIssueIds.length > 0 })
  const cardsByIssue = useMemo(() => indexIssueCards(cardsQuery.data), [cardsQuery.data])

  if (recovery.isPending) return <p role="status">Checking Reading Plan references…</p>
  if (recovery.isError || !recovery.data) {
    return <p className="text-sm text-[var(--theme-text-muted)]">
      The repair preview is unavailable. No changes were made.
    </p>
  }
  const preview = recovery.data
  if (preview.status === 'linked') return null
  if (preview.status === 'ambiguous') {
    return <p role="alert">This plan has multiple authoritative sources. It needs an explicit source decision; nothing was changed.</p>
  }

  const selected = preview.candidates.find((candidate) => candidate.list_id === selectedId)
  return (
    <section
      className="mt-4 space-y-4 rounded-xl border border-[var(--theme-warning)] p-4 text-[var(--theme-text-primary)]"
      aria-label="Recover missing Reading List"
      data-testid="orphaned-plan-recovery"
    >
      <h2 className="text-lg font-bold">Recover this Reading Plan</h2>
      <p>
        This Plan still exists, but its original Reading List identity was deleted.
        The saved Plan has {preview.retained_steps.length} surviving issue references.
        Creating another list with the same name does not restore its identity.
      </p>
      <details
        open={showSavedRefs}
        onToggle={(event) => setShowSavedRefs(event.currentTarget.open)}
      >
        <summary className="cursor-pointer font-semibold">Show saved Plan references</summary>
        <StepNames steps={preview.retained_steps} cardsByIssue={cardsByIssue} />
      </details>
      <p>
        Choose an existing Reading List as the new authority, or{' '}
        <Link className="underline" to={`/continuity-plans/${planId}/edit?authoring=1`}>open the Plan authoring UI</Link>{' '}
        with the issues and order you want. This does not recover deleted issues automatically.
      </p>
      <label className="block space-y-2">
        <span className="font-semibold">Reading List to relink</span>
        <select
          className="w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
          value={selectedId ?? ''}
          onChange={(event) => {
            setSelectedId(event.target.value ? Number(event.target.value) : null)
            setAcknowledged(false)
            apply.reset()
          }}
        >
          <option value="">Choose a Reading List</option>
          {preview.candidates.map((candidate) => (
            <option key={candidate.list_id} value={candidate.list_id}>
              {candidate.name} ({candidate.steps.length} entries)
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <>
          <CandidateChanges
            candidate={selected}
            cardsByIssue={cardsByIssue}
            showFullOrder={showFullOrder}
            onToggleFullOrder={setShowFullOrder}
          />
          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-1"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span>
              I reviewed the differences and authorize this list as the reading-order source.
              Existing Plan snapshots, reads, ratings, and events must remain untouched.
            </span>
          </label>
          <button
            type="button"
            disabled={!acknowledged || apply.isPending}
            className="min-h-11 rounded-xl bg-[var(--theme-primary-action)] px-4 font-bold text-[var(--theme-primary-action-text)] disabled:opacity-50"
            onClick={() => void apply.mutate({
              list_id: selected.list_id,
              expected_plan_updated_at: preview.plan_updated_at,
              expected_list_updated_at: selected.list_updated_at,
              confirm: true,
            })}
          >
            {apply.isPending ? 'Relinking…' : `Relink to ${selected.name}`}
          </button>
          {apply.isError && (
            <p role="alert" className="text-[var(--theme-error)]">
              {apply.error.message}. Refresh the preview before retrying.
              <button
                type="button"
                className="ml-2 underline"
                onClick={() => void recovery.refetch()}
              >Refresh preview</button>
            </p>
          )}
        </>
      )}
    </section>
  )
}
