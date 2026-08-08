import { Link } from 'react-router-dom'
import type { DependencyGroupSummary } from '../services/api-dependency-groups'

interface CrossoverTagsProps {
  groups: DependencyGroupSummary[]
  align?: 'start' | 'center'
  label?: string
}

export function CrossoverTags({
  groups,
  align = 'start',
  label = 'Crossovers',
}: CrossoverTagsProps) {
  if (groups.length === 0) return null

  return (
    <section aria-label={label} className="min-w-0">
      <ul
        className={`flex max-w-full flex-wrap gap-2 ${align === 'center' ? 'justify-center' : 'justify-start'}`}
      >
        {groups.map((group) => (
          <li key={group.id} className="min-w-0 max-w-full">
            <Link
              to={`/crossovers?group=${group.id}`}
              className="block max-w-full truncate rounded-lg border border-violet-700/30 bg-violet-900/20 px-3 py-1.5 text-xs font-bold text-violet-300 transition hover:border-violet-500/60 hover:bg-violet-900/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400"
              title={group.name}
            >
              {group.name}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
