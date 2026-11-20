import type { ContinuityPlanListItem } from '../services/api-continuity-plans'

interface CblAdoptionTargetFieldsetProps {
  plans: ContinuityPlanListItem[]
  selectedPlanId: number | null
  sourceAlreadyAdopted: boolean
  disabled: boolean
  onChoose: (planId: number) => void
}

/** Require the reader to name the exact existing plan a CBL adoption may update. */
export function CblAdoptionTargetFieldset({
  plans,
  selectedPlanId,
  sourceAlreadyAdopted,
  disabled,
  onChoose,
}: CblAdoptionTargetFieldsetProps) {
  return (
    <fieldset className="space-y-3 rounded-xl border border-[var(--theme-border)] p-3">
      <legend className="px-1 text-sm font-bold text-[var(--theme-text-primary)]">
        Choose an existing Reading Plan
      </legend>
      <p className="text-sm text-[var(--theme-text-muted)]">
        {sourceAlreadyAdopted
          ? 'This source already belongs to a Reading Plan. Choose the exact plan to update; nothing is selected automatically.'
          : 'A Reading Plan with this source’s name already exists. Choose the exact plan to update, or Cancel to leave it unchanged. Nothing is selected automatically.'}
      </p>
      <div className="space-y-2">
        {plans.map((plan) => (
          <label
            key={plan.id}
            className="flex min-h-11 items-center gap-3 rounded-lg border border-[var(--theme-border)] px-3 py-2 text-sm text-[var(--theme-text-primary)]"
          >
            <input
              type="radio"
              name="cbl-adoption-target"
              value={plan.id}
              checked={selectedPlanId === plan.id}
              disabled={disabled}
              onChange={() => onChoose(plan.id)}
              aria-label={`Update ${plan.name} (Reading Plan #${plan.id})`}
            />
            <span className="min-w-0 flex-1 font-bold">{plan.name}</span>
            <span className="shrink-0 text-xs text-[var(--theme-text-dim)]">
              #{plan.id} · {plan.step_count} {plan.step_count === 1 ? 'step' : 'steps'}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
