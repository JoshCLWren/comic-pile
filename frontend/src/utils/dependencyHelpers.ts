import type { IssueDependenciesResponse, IssueDependencyEdge } from '../types'

/**
 * Generate a tooltip string showing dependency information for an issue.
 * @param deps - Issue dependencies response object
 * @returns Formatted tooltip string or null if no dependencies
 */
export function getDependencyTooltip(deps: IssueDependenciesResponse | undefined): string | null {
  if (!deps || (deps.incoming.length === 0 && deps.outgoing.length === 0)) {
    return null
  }

  const parts: string[] = []

  if (deps.incoming.length > 0) {
    parts.push('Blocked by:')
    deps.incoming.forEach((edge) => {
      parts.push(` ← ${edge.source_thread_title} #${edge.source_issue_number}`)
    })
  }

  if (deps.outgoing.length > 0) {
    parts.push('Blocks:')
    deps.outgoing.forEach((edge) => {
      // For outgoing edges, the edge contains the target issue info
      // (reusing the source_* fields to represent the target)
      parts.push(` → ${edge.source_thread_title} #${edge.source_issue_number}`)
    })
  }

  return parts.join('\n')
}
