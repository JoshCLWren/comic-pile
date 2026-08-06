import { CrossoverTags } from '../../../components/CrossoverTags'
import { useDependencyGroups } from '../../../hooks/useDependencyGroups'

interface ReadingOrderGroupsProps {
  threadId: number | null | undefined
}

export function ReadingOrderGroups({ threadId }: ReadingOrderGroupsProps) {
  const { groups, isLoading, error } = useDependencyGroups(threadId)

  if (threadId == null) return null

  if (isLoading) {
    return (
      <div className="text-center" role="status" aria-live="polite">
        <span className="text-[10px] font-bold uppercase tracking-wider text-stone-500">
          Loading crossovers…
        </span>
      </div>
    )
  }

  if (error) {
    return (
      <p className="text-center text-[10px] font-bold text-rose-500" role="alert">
        Unable to load crossovers.
      </p>
    )
  }

  if (groups.length === 0) return null

  return (
    <section aria-labelledby="crossovers-heading" className="space-y-2 text-center">
      <h3
        id="crossovers-heading"
        className="text-[10px] font-black uppercase tracking-[0.2em] text-stone-500"
      >
        Crossovers
      </h3>
      <CrossoverTags groups={groups} align="center" label="Crossover memberships" />
    </section>
  )
}
