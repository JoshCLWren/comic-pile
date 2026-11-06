import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  readingPlanRecoveryApi,
  type RecoveryCandidate,
  type RecoveryStep,
} from '../services/api-reading-plan-recovery'

function StepNames({ steps }: { steps: RecoveryStep[] }) {
  return (
    <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-[var(--theme-text-muted)]">
      {steps.map((step) => (
        <li key={step.issue_id}>
          {step.label} <span className="text-xs">(issue ID {step.issue_id})</span>
        </li>
      ))}
    </ul>
  )
}

function CandidateChanges({ candidate }: { candidate: RecoveryCandidate }) {
  return (
    <div className="mt-3 space-y-3 text-sm" data-testid="plan-recovery-diff">
      <p className="font-semibold text-[var(--theme-text-primary)]">
        Preview: {candidate.steps.length} entries, {candidate.mode} mode
      </p>
      {candidate.added_steps.length > 0 && (
        <div>
          <p>Newly authoritative issues ({candidate.added_steps.length}):</p>
          <StepNames steps={candidate.added_steps} />
        </div>
      )}
      {candidate.removed_steps.length > 0 && (
        <div>
          <p>Saved Plan issues absent from this list ({candidate.removed_steps.length}):</p>
          <StepNames steps={candidate.removed_steps} />
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
      <details>
        <summary className="cursor-pointer font-semibold">View the complete proposed reading order</summary>
        <StepNames steps={candidate.steps} />
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
  const client = useQueryClient()
  const recovery = useQuery({
    queryKey: ['reading-plan-recovery', planId],
    queryFn: () => readingPlanRecoveryApi.preview(planId),
  })
  // The API's relink method is a two-argument function, so invoke it through
  // a one-argument mutation wrapper to keep the current plan ID explicit.
  const apply = useMutation({
    mutationFn: async ({ listId, planUpdatedAt, listUpdatedAt }: {
      listId: number
      planUpdatedAt: string
      listUpdatedAt: string
    }) => readingPlanRecoveryApi.relink(planId, {
      list_id: listId,
      expected_plan_updated_at: planUpdatedAt,
      expected_list_updated_at: listUpdatedAt,
      confirm: true,
    }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['reading-plan-recovery', planId] })
      onRecovered()
    },
  })

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
      <details>
        <summary className="cursor-pointer font-semibold">Show saved Plan references</summary>
        <StepNames steps={preview.retained_steps} />
      </details>
      <p>
        Choose an existing Reading List as the new authority, or{' '}
        <Link className="underline" to="/continuity-plans/new">open the Plan authoring UI</Link>{' '}
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
          <CandidateChanges candidate={selected} />
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
              listId: selected.list_id,
              planUpdatedAt: preview.plan_updated_at,
              listUpdatedAt: selected.list_updated_at,
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
