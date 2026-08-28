import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { continuityPlansApi, type ContinuityPlanListItem } from '../services/api-continuity-plans'

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
  const [plans, setPlans] = useState<ContinuityPlanListItem[] | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setIsLoading(true)
    setLoadError(null)
    void continuityPlansApi
      .list()
      .then((loaded) => active && setPlans(loaded))
      .catch((error) => active && setLoadError(error instanceof Error ? error.message : 'Unable to load plans.'))
      .finally(() => active && setIsLoading(false))
    return () => { active = false }
  }, [])

  const confirmDelete = useCallback(async () => {
    if (deleteTargetId == null) return
    setIsDeleting(true)
    setDeleteError(null)
    try {
      await continuityPlansApi.delete(deleteTargetId)
      setPlans((current) => (current ? current.filter((plan) => plan.id !== deleteTargetId) : current))
      setDeleteTargetId(null)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Delete failed.')
    } finally {
      setIsDeleting(false)
    }
  }, [deleteTargetId])

  if (isLoading) return <p role="status" className="text-stone-400">Loading plans…</p>
  if (loadError) return <div role="alert" className="rounded-2xl border border-red-800 bg-red-950/30 p-4 text-red-200">{loadError}</div>

  return (
    <section className="space-y-5" aria-labelledby="plans-heading">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.2em] text-amber-500">Continuity</p>
          <h1 id="plans-heading" className="mt-1 text-3xl font-black text-stone-100">Reading plans</h1>
          <p className="mt-2 text-sm text-stone-400">Saved sequential reading plans, ordered last-saved first.</p>
        </div>
      </header>

      {!plans || plans.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-stone-700 p-8 text-center">
          <p className="text-lg font-bold text-stone-100">No reading plans yet</p>
          <p className="mt-2 text-sm text-stone-500">Create your first plan from the sequential planner.</p>
          <button
            type="button"
            onClick={() => navigate('/continuity-plans/new')}
            className="mt-4 min-h-11 rounded-xl bg-amber-500 px-5 font-black text-stone-950"
          >
            Create a plan
          </button>
        </div>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {plans.map((plan) => {
            const isDeletingThis = isDeleting && deleteTargetId === plan.id
            return (
              <li
                key={plan.id}
                data-testid={`plan-card-${plan.id}`}
                className="flex flex-col gap-3 rounded-2xl border border-stone-800 bg-stone-900/50 p-4"
              >
                <button
                  type="button"
                  onClick={() => navigate(`/continuity-plans/${plan.id}`)}
                  className="flex-1 text-left"
                >
                  <p className="truncate text-base font-black text-stone-100">{plan.name}</p>
                  <p className="mt-1 text-xs text-stone-500">
                    {plan.lane_count} {plan.lane_count === 1 ? 'lane' : 'lanes'} · {plan.step_count} {plan.step_count === 1 ? 'step' : 'steps'}
                  </p>
                  <p className="mt-1 text-xs text-stone-600">Last saved {formatDate(plan.updated_at)}</p>
                </button>
                {deleteTargetId === plan.id ? (
                  <div className="flex flex-col gap-2 border-t border-stone-800 pt-3">
                    <p className="text-xs text-red-300">Delete this plan? Associated rules will also be removed.</p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setDeleteTargetId(null)}
                        disabled={isDeletingThis}
                        className="min-h-11 flex-1 rounded-xl border border-stone-700 font-bold disabled:opacity-50"
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
                    {deleteError && deleteTargetId === plan.id && (
                      <p role="alert" className="text-xs text-red-300">{deleteError}</p>
                    )}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => { setDeleteTargetId(plan.id); setDeleteError(null) }}
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