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
          Loading reading-order groups…
        </span>
      </div>
    )
  }

  if (error) {
    return (
      <p className="text-center text-[10px] font-bold text-rose-500" role="alert">
        Unable to load reading-order groups.
      </p>
    )
  }

  if (groups.length === 0) return null

  return (
    <section aria-labelledby="reading-order-groups-heading" className="space-y-2 text-center">
      <h3
        id="reading-order-groups-heading"
        className="text-[10px] font-black uppercase tracking-[0.2em] text-stone-500"
      >
        Reading-order groups
      </h3>
      <ul className="flex flex-wrap justify-center gap-2">
        {groups.map((group) => (
          <li
            key={group.id}
            className="max-w-full break-words rounded-lg border border-violet-700/30 bg-violet-900/20 px-3 py-1.5 text-xs font-bold text-violet-300"
          >
            {group.name}
          </li>
        ))}
      </ul>
    </section>
  )
}
