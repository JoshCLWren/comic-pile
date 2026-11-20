import { useMemo, useState } from 'react'
import type { ThreadListItem, ThreadQueueExclusionGroup } from '../../types'

interface ExcludedThreadsSectionProps {
  threads: ThreadListItem[]
  isRestoring: boolean
  error: string | null
  onRestore: (threadId: number) => void
  onRestoreGroup: (groupId: number) => void
}

interface ExclusionGroupView {
  group: ThreadQueueExclusionGroup
  threads: ThreadListItem[]
}

function sourceKindLabel(kind: ThreadQueueExclusionGroup['source_kind']): string {
  if (kind === 'reading_list') return 'Reading list'
  if (kind === 'reading_plan') return 'Reading plan'
  return 'Crossover'
}

/**
 * Discoverable library view for series removed from the queue (#3807, #5435).
 *
 * "Remove from Queue" is non-destructive: the thread keeps its issues, read
 * state, ratings, mappings, and reading-plan memberships. Excluded series are
 * grouped by the list/plan/crossover they were removed with so a whole group
 * can be restored at once, while individual restores remain available.
 */
export default function ExcludedThreadsSection({
  threads,
  isRestoring,
  error,
  onRestore,
  onRestoreGroup,
}: ExcludedThreadsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  const { groups, ungrouped } = useMemo(() => {
    const groupMap = new Map<number, ExclusionGroupView>()
    const loose: ThreadListItem[] = []
    for (const thread of threads) {
      const group = thread.queue_exclusion_group
      if (!group) {
        loose.push(thread)
        continue
      }
      const existing = groupMap.get(group.id)
      if (existing) {
        existing.threads.push(thread)
      } else {
        groupMap.set(group.id, { group, threads: [thread] })
      }
    }
    return { groups: Array.from(groupMap.values()), ungrouped: loose }
  }, [threads])

  if (threads.length === 0) return null

  return (
    <section
      className="space-y-4"
      aria-labelledby="removed-from-queue-heading"
      data-testid="excluded-threads-section"
    >
      <header className="flex items-center justify-between gap-3 px-2">
        <div className="min-w-0">
          <h2
            id="removed-from-queue-heading"
            className="text-lg md:text-xl font-black uppercase text-[var(--theme-text-primary)]"
          >
            Removed from Queue
          </h2>
          <p className="text-[10px] font-bold text-[var(--theme-text-muted)] uppercase tracking-widest">
            {threads.length} series kept out of the queue with history intact
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded((expanded) => !expanded)}
          aria-expanded={isExpanded}
          aria-controls="excluded-thread-list"
          className="h-8 md:h-10 px-3 md:px-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)]"
        >
          {isExpanded ? 'Hide Removed' : `Show Removed (${threads.length})`}
        </button>
      </header>

      <div id="excluded-thread-list" className="space-y-4" hidden={!isExpanded}>
        {error && (
          <p
            role="alert"
            className="px-2 text-sm text-[var(--theme-error)]"
            data-testid="excluded-threads-error"
          >
            {error}
          </p>
        )}

        {groups.map(({ group, threads: groupThreads }) => (
          <div
            key={group.id}
            className="surface-panel p-4 space-y-3"
            data-testid="excluded-group"
            data-group-id={group.id}
            data-group-source-kind={group.source_kind}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] font-bold text-[var(--theme-text-muted)] uppercase tracking-widest">
                  {sourceKindLabel(group.source_kind)}
                </p>
                <p className="text-sm font-black text-[var(--theme-text-primary)] truncate">{group.source_name}</p>
                <p className="text-xs text-[var(--theme-text-dim)]">
                  {groupThreads.length} shown here (Restore All restores the whole group)
                </p>
              </div>
              <button
                type="button"
                onClick={() => onRestoreGroup(group.id)}
                disabled={isRestoring}
                aria-label={`Restore all series removed with ${group.source_name}`}
                className="px-3 py-2 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg text-sm font-semibold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
              >
                Restore All to Queue
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {groupThreads.map((thread) => (
                <div key={thread.id} className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-black text-[var(--theme-text-primary)] truncate">{thread.title}</p>
                      <p className="text-[8px] font-black text-[var(--theme-text-muted)] uppercase tracking-widest">
                        {thread.format}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => onRestore(thread.id)}
                      disabled={isRestoring}
                      aria-label={`Restore ${thread.title} to queue`}
                      className="px-3 py-1.5 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg text-sm font-semibold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
                    >
                      Restore
                    </button>
                  </div>
                  <p className="text-xs text-[var(--theme-text-dim)]">{thread.issues_remaining} unread preserved</p>
                </div>
              ))}
            </div>
          </div>
        ))}

        {ungrouped.length > 0 && (
          <div className="space-y-3" data-testid="excluded-ungrouped">
            {groups.length > 0 && (
              <p className="px-2 text-[10px] font-bold text-[var(--theme-text-muted)] uppercase tracking-widest">
                Individually removed series
              </p>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {ungrouped.map((thread) => (
                <div key={thread.id} className="surface-panel p-4 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-black text-[var(--theme-text-primary)] truncate">{thread.title}</p>
                      <p className="text-[8px] font-black text-[var(--theme-text-muted)] uppercase tracking-widest">
                        {thread.format}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => onRestore(thread.id)}
                      disabled={isRestoring}
                      aria-label={`Restore ${thread.title} to queue`}
                      className="px-3 py-1.5 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg text-sm font-semibold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
                    >
                      Restore to Queue
                    </button>
                  </div>
                  <p className="text-xs text-[var(--theme-text-dim)]">{thread.issues_remaining} unread preserved</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
