import { useEffect, useMemo, useState } from 'react'
import CompactIssueCardTrigger from '../../../components/CompactIssueCardTrigger'
import Modal from '../../../components/Modal'
import { useIssueCards } from '../../../hooks/useIssueCards'
import { useThreadIssuePages } from '../../../hooks/useThreadIssues'
import { issuesApi } from '../../../services/api-issues'
import { threadsApi } from '../../../services/api-threads'
import type { Issue, ThreadListItem, ThreadListResponse } from '../../../types'
import type { RollBootstrapThread } from '../../../types/rollBootstrap'
import { getApiErrorDetail } from '../../../utils/apiError'
import { buildManualPickerOptions } from '../manualPickerOptions'
import { ManualPickerSearch } from './ManualPickerSearch'

const EMPTY_ISSUES: Issue[] = []

async function collectThreadPages(
  loadPage: (pageToken: string | null) => Promise<ThreadListResponse>,
): Promise<ThreadListItem[]> {
  const threads: ThreadListItem[] = []
  let pageToken: string | null = null
  do {
    const page = await loadPage(pageToken)
    threads.push(...page.threads)
    pageToken = page.next_page_token ?? null
  } while (pageToken)
  return threads
}

/** Load every owned series in parallel, including series outside the active Queue. */
async function loadLibraryThreads(): Promise<ThreadListItem[]> {
  const [active, completed, excluded] = await Promise.all([
    collectThreadPages((pageToken) => threadsApi.list({ page_size: 200 }, pageToken)),
    collectThreadPages((pageToken) =>
      threadsApi.listCompleted(undefined, undefined, pageToken, 200),
    ),
    collectThreadPages((pageToken) =>
      threadsApi.listExcluded(undefined, undefined, pageToken, 200),
    ),
  ])
  return [...new Map([...active, ...completed, ...excluded].map((thread) => [thread.id, thread])).values()]
}

interface ManualIssuePickerModalProps {
  snoozedThreads: RollBootstrapThread[]
  onClose: () => void
}

/**
 * Exact-issue manual reading, deliberately separate from the series-level Roll
 * override. Series and issue reads happen only after this dialog is opened;
 * saving through the shared card uses the direct native issue command and
 * leaves Roll pending selection, die and queue semantics untouched.
 */
export default function ManualIssuePickerModal({
  snoozedThreads,
  onClose,
}: ManualIssuePickerModalProps) {
  const [threads, setThreads] = useState<ThreadListItem[] | null>(null)
  const [threadError, setThreadError] = useState<unknown>(null)
  const [threadLoadRevision, setThreadLoadRevision] = useState(0)
  const [selectedThreadId, setSelectedThreadId] = useState('')
  const [hasSearched, setHasSearched] = useState(false)
  const [issueFilter, setIssueFilter] = useState('')

  useEffect(() => {
    let cancelled = false
    setThreads(null)
    setThreadError(null)
    loadLibraryThreads()
      .then((loaded) => {
        if (!cancelled) setThreads(loaded)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setThreads([])
          setThreadError(error)
        }
      })
    return () => {
      cancelled = true
    }
  }, [threadLoadRevision])

  const selectedId = selectedThreadId ? Number(selectedThreadId) : null
  const issuePages = useThreadIssuePages(selectedId, { enabled: hasSearched })
  const loadedIssues = hasSearched ? issuePages.issues : EMPTY_ISSUES
  const issueIds = useMemo(() => loadedIssues.map((issue) => issue.id), [loadedIssues])
  const cardsQuery = useIssueCards(issueIds, { enabled: hasSearched && issueIds.length > 0 })
  const cardsById = useMemo(
    () => new Map((cardsQuery.data ?? []).map((card) => [card.issue_id, card])),
    [cardsQuery.data],
  )

  const groups = useMemo(() => {
    const snoozedIds = new Set(snoozedThreads.map((thread) => thread.id))
    const libraryThreads = (threads ?? []).filter((thread) => !snoozedIds.has(thread.id))
    const built = buildManualPickerOptions({
      activeThreads: libraryThreads,
      snoozedThreads,
    })
    const threadsById = new Map(libraryThreads.map((thread) => [thread.id, thread]))
    return {
      ...built,
      activeOptions: built.activeOptions.map((option) => {
        const status = threadsById.get(option.id)?.status
        if (status !== 'completed' && status !== 'excluded') return option
        return {
          ...option,
          label: `${option.label} · ${status === 'completed' ? 'Completed' : 'Excluded'}`,
        }
      }),
    }
  }, [snoozedThreads, threads])

  const selectedThread =
    (threads ?? []).find((thread) => thread.id === selectedId)
    ?? snoozedThreads.find((thread) => thread.id === selectedId)
    ?? null
  const normalizedFilter = issueFilter.trim().toLowerCase().replace(/^#/, '')
  const visibleIssues = normalizedFilter
    ? loadedIssues.filter((issue) =>
        issue.issue_number.toLowerCase().includes(normalizedFilter)
        || String(issue.id) === normalizedFilter,
      )
    : loadedIssues

  function selectThread(value: string) {
    setSelectedThreadId(value)
    setHasSearched(false)
    setIssueFilter('')
  }

  return (
    <Modal isOpen title="Read an issue" onClose={onClose} size="large" data-testid="manual-issue-picker">
      <p className="text-sm text-[var(--theme-text-muted)]">
        Find any owned issue, including completed, excluded, inactive or already-read issues.
        Direct reading does not roll the die, change a pending Roll selection, or move the Queue.
      </p>

      <div className="space-y-2">
        <ManualPickerSearch
          activeOptions={groups.activeOptions}
          snoozedOptions={groups.snoozedOptions}
          value={selectedThreadId}
          onChange={selectThread}
          disabled={threads == null}
          placeholder="Search every series…"
          noMatchText="No matching series in your library"
        />
        {threads == null && !threadError && (
          <p role="status" className="text-sm text-[var(--theme-text-muted)]">Loading your series…</p>
        )}
        {threadError != null && (
          <p role="alert" className="text-sm text-[var(--theme-error)]">
            Could not load your series: {getApiErrorDetail(threadError)}
            <button
              type="button"
              onClick={() => setThreadLoadRevision((revision) => revision + 1)}
              className="ml-2 min-h-11 font-bold underline"
            >
              Retry
            </button>
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={!selectedThread || issuePages.isFetching}
          onClick={() => {
            if (hasSearched) void issuePages.refetch()
            else setHasSearched(true)
          }}
          className="min-h-11 rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-[var(--theme-primary-action-text)] transition-colors hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50"
        >
          {issuePages.isFetching ? 'Loading issues…' : hasSearched ? 'Refresh issues' : 'Find issues'}
        </button>
        {selectedThread && <p className="text-sm text-[var(--theme-text-muted)]">{selectedThread.title}</p>}
      </div>

      {hasSearched && (
        <section aria-label="Issue results" className="space-y-3">
          {issuePages.isError ? (
            <p role="alert" className="text-sm text-[var(--theme-error)]">
              Could not load issues: {getApiErrorDetail(issuePages.error)}
              <button
                type="button"
                onClick={() => void issuePages.refetch()}
                className="ml-2 min-h-11 font-bold underline"
              >
                Retry
              </button>
            </p>
          ) : (
            <>
              <div className="space-y-1">
                <label htmlFor="manual-issue-filter" className="block text-sm font-medium text-[var(--theme-text-primary)]">
                  Filter loaded issues
                </label>
                <input
                  id="manual-issue-filter"
                  type="search"
                  value={issueFilter}
                  onChange={(event) => setIssueFilter(event.target.value)}
                  placeholder="Issue number, e.g. 10 or Annual 1"
                  className="form-control w-full rounded-xl px-3 py-2 text-base"
                />
              </div>

              {!issuePages.isPending && loadedIssues.length === 0 && (
                <p className="text-sm text-[var(--theme-text-muted)]">This series has no owned issues.</p>
              )}
              {!issuePages.isPending && loadedIssues.length > 0 && visibleIssues.length === 0 && (
                <p className="text-sm text-[var(--theme-text-muted)]">
                  No loaded issue matches. Clear the filter or load more issues.
                </p>
              )}
              {cardsQuery.isPending && loadedIssues.length > 0 && (
                <p role="status" className="text-xs text-[var(--theme-text-muted)]">Loading issue details…</p>
              )}

              <div className="grid gap-2 md:grid-cols-2">
                {visibleIssues.map((issue) => (
                  <CompactIssueCardTrigger
                    key={issue.id}
                    issueId={issue.id}
                    threadTitle={selectedThread?.title ?? ''}
                    issueNumber={issue.issue_number}
                    status={issue.status}
                    card={cardsById.get(issue.id)}
                    actionLabel="Open Read / Rate / Map"
                  />
                ))}
              </div>

              {issuePages.hasNextPage && (
                <button
                  type="button"
                  onClick={() => void issuePages.fetchNextPage()}
                  disabled={issuePages.isFetchingNextPage}
                  className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
                >
                  {issuePages.isFetchingNextPage
                    ? 'Loading more…'
                    : `Load more issues (${loadedIssues.length} of ${issuePages.totalCount})`}
                </button>
              )}
            </>
          )}
        </section>
      )}
    </Modal>
  )
}
