import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import GlossaryLink from '../components/GlossaryLink'
import { useDeleteReadingPlan, useReadingPlans } from '../hooks/useReadingPlans'

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

export default function ContinuityPlansIndexPage() {
  const navigate = useNavigate()
  const plansQuery = useReadingPlans()
  const deletePlan = useDeleteReadingPlan()
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null)

  const plans = plansQuery.data ?? []
  const confirmDelete = () => {
    if (deleteTargetId == null) return
    deletePlan.mutate(deleteTargetId, { onSuccess: () => setDeleteTargetId(null) })
  }

  if (plansQuery.isPending) return <p role="status" className="text-[var(--theme-text-muted)]">Loading plans…</p>
  if (plansQuery.isError) return <div role="alert" className="rounded-2xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-4 text-[var(--theme-danger)]">{plansQuery.error.message || 'Unable to load plans.'}</div>

  return (
    <section className="space-y-5" aria-labelledby="plans-heading">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 id="plans-heading" className="text-2xl font-black text-[var(--theme-text-primary)]">Reading Plans</h1>
          <p className="mt-2 text-sm text-[var(--theme-text-muted)]">Your saved reading order, including plans backed by CBL sources.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => navigate('/continuity-plans/new')}
            className="min-h-11 rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-black hover:bg-[var(--theme-primary-action-hover)]"
          >
            New Reading Plan
          </button>
          <button
            type="button"
            onClick={() => navigate(plans[0] ? `/continuity-plans/${plans[0].id}?addFrom=cbl` : '/continuity-plans/new?addFrom=cbl')}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
          >
            Add from CBL
          </button>
        </div>
      </header>

      {plans.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-lg font-bold text-[var(--theme-text-primary)]">No reading plans yet</p>
          <p className="mx-auto mt-2 max-w-xl text-sm text-[var(--theme-text-muted)]">
            A reading plan is a saved arrangement of issues, series, and crossovers in one or more
            reading lanes — so you can read a storyline in order, even when it hops across crossovers
            and your Queue.{' '}
            <GlossaryLink id="continuity-plan">What is a continuity plan?</GlossaryLink>
          </p>
          <p className="mt-2 text-sm text-[var(--theme-text-muted)]">Create a plan yourself or start one from a saved CBL source.</p>
        </div>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {plans.map((plan) => {
            const isDeletingThis = deletePlan.isPending && deleteTargetId === plan.id
            return (
              <li
                key={plan.id}
                data-testid={`plan-card-${plan.id}`}
                className="flex flex-col gap-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
              >
                <button
                  type="button"
                  onClick={() => navigate(`/continuity-plans/${plan.id}`)}
                  className="flex-1 text-left"
                >
                  <p className="truncate text-base font-black text-[var(--theme-text-primary)]">{plan.name}</p>
                  <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
                    {plan.lane_count} {plan.lane_count === 1 ? 'lane' : 'lanes'} · {plan.step_count} {plan.step_count === 1 ? 'step' : 'steps'}
                  </p>
                  {plan.source_paths.length > 0 && (
                    <div className="mt-3 rounded-lg border border-[var(--theme-continuity-accent)] p-2">
                      <span className="text-xs font-black text-[var(--theme-continuity-accent)]">CBL-backed</span>
                      <span className="ml-2 text-xs text-[var(--theme-text-muted)]">Source: {plan.source_paths[0]}</span>
                      {plan.source_paths.length > 1 && <span className="ml-1 text-xs text-[var(--theme-text-dim)]">+{plan.source_paths.length - 1} more</span>}
                    </div>
                  )}
                  <p className="mt-1 text-xs text-[var(--theme-text-dim)]">Last saved {formatDate(plan.updated_at)}</p>
                </button>
                {deleteTargetId === plan.id ? (
                  <div className="flex flex-col gap-2 border-t border-[var(--theme-border)] pt-3">
                    <p className="text-xs text-red-300">Delete this plan? Associated rules will also be removed.</p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setDeleteTargetId(null)}
                        disabled={isDeletingThis}
                        className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] font-bold disabled:opacity-50"
                      >
                        Keep
                      </button>
                      <button
                        type="button"
                        onClick={confirmDelete}
                        disabled={isDeletingThis}
                        className="min-h-11 flex-1 rounded-xl bg-red-500 font-black text-white disabled:opacity-50"
                      >
                        {isDeletingThis ? 'Deleting…' : 'Delete'}
                      </button>
                    </div>
                    {deletePlan.isError && deleteTargetId === plan.id && (
                      <p role="alert" className="text-xs text-[var(--theme-danger)]">{deletePlan.error.message || 'Delete failed.'}</p>
                    )}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => { deletePlan.reset(); setDeleteTargetId(plan.id) }}
                    className="min-h-9 self-end rounded-lg border border-red-900 px-3 text-xs font-bold text-red-300 hover:bg-red-900/30"
                  >
                    Delete
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
