import { useEffect, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { ComicIssueCard } from './ComicIssueCard'
import { useIssueCards } from '../hooks/useIssueCards'
import { issuesApi } from '../services/api-issues'
import { queryKeys } from '../query/queryKeys'
import { getApiErrorDetail } from '../utils/apiError'
import type { Issue } from '../types'

interface DirectReadIssuePanelProps {
  threadId: number
  threadTitle: string
  /** Exact issue already presented by Roll, when one is known. */
  preferredIssueId?: number | null
}

/**
 * Exact-owned-issue manual reading, shared by Queue and Roll.
 *
 * Opening this panel and choosing an issue perform only authenticated reads.
 * Neither the next-unread lookup nor the optional all-issues picker checks
 * automatic Roll eligibility. Only ComicIssueCard Save writes, through the
 * owner-scoped, idempotent Rust v2 direct command. That command never creates
 * or consumes a pending random Roll offer.
 */
export function DirectReadIssuePanel({
  threadId,
  threadTitle,
  preferredIssueId,
}: DirectReadIssuePanelProps) {
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null)
  const [browseOpen, setBrowseOpen] = useState(false)

  const nextUnread = useQuery({
    queryKey: queryKeys.thread.issuePage(threadId, { pageToken: null, pageSize: 1, status: 'unread' }),
    queryFn: async () => {
      const response = await issuesApi.list(threadId, { status: 'unread', page_size: 1 })
      return response.issues[0] ?? null
    },
    enabled: preferredIssueId == null,
    retry: false,
  })
  const preferredIssue = useQuery({
    queryKey: queryKeys.thread.manualIssue(preferredIssueId ?? 0),
    queryFn: () => issuesApi.get(preferredIssueId!),
    enabled: preferredIssueId != null,
    retry: false,
  })
  const initialIssue = preferredIssueId == null ? nextUnread.data : preferredIssue.data

  // Pin the exact issue once resolved. A successful Save may change the
  // server's "next unread" projection, but cannot silently switch this editor
  // to a different comic while the reader is still looking at it.
  useEffect(() => {
    if (initialIssue && selectedIssue == null) setSelectedIssue(initialIssue)
  }, [initialIssue, selectedIssue])

  // Browse is opt-in and paginated; opening dozens of Queue rows must never
  // fetch a whole library or start one request per owned issue.
  const browse = useInfiniteQuery({
    queryKey: queryKeys.thread.directReadBrowse(threadId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => issuesApi.list(threadId, {
      page_size: 50,
      page_token: pageParam ?? undefined,
    }),
    getNextPageParam: (lastPage) => lastPage.next_page_token ?? undefined,
    enabled: browseOpen,
    retry: false,
  })
  const issue = selectedIssue ?? initialIssue ?? null
  const cards = useIssueCards(issue ? [issue.id] : [], { enabled: issue != null })
  const card = cards.data?.find((item) => item.issue_id === issue?.id) ?? null
  const wrongThread = issue != null && issue.thread_id !== threadId
  const lookup = preferredIssueId == null ? nextUnread : preferredIssue
  const choices = browse.data?.pages.flatMap((page) => page.issues) ?? []

  return (
    <section className="space-y-3" data-testid="direct-read-issue-panel">
      <p className="text-xs text-[var(--theme-text-muted)]">
        Choose an owned issue to read or rate. Automatic Roll prerequisites are advisory only.
        Nothing is saved until you select Save; your pending Roll and die are preserved.
      </p>
      {lookup.isPending && !selectedIssue && (
        <p role="status" className="text-sm text-[var(--theme-text-muted)]">Loading exact issue…</p>
      )}
      {lookup.isError && !selectedIssue && (
        <div role="alert" className="space-y-2 text-sm text-[var(--theme-danger)]">
          <p>Could not load the owned issue: {getApiErrorDetail(lookup.error)}</p>
          <button type="button" onClick={() => void lookup.refetch()} className="min-h-11 font-bold underline">
            Retry issue lookup
          </button>
        </div>
      )}
      {wrongThread && (
        <p role="alert" className="text-sm text-[var(--theme-danger)]">
          This issue does not belong to the selected series.
        </p>
      )}
      {issue && !wrongThread && (
        <>
          {cards.isError && (
            <p role="alert" className="text-xs text-[var(--theme-danger)]">
              Cover and rating details are unavailable: {getApiErrorDetail(cards.error)}
              <button type="button" onClick={() => void cards.refetch()} className="ml-2 min-h-9 font-bold underline">
                Retry details
              </button>
            </p>
          )}
          <ComicIssueCard
            key={issue.id}
            issueId={issue.id}
            card={card}
            threadTitle={threadTitle}
            issueNumber={String(issue.issue_number)}
            status={issue.status}
            variant="compact"
          />
        </>
      )}
      {!lookup.isPending && !lookup.isError && !issue && (
        <p role="status" className="text-sm text-[var(--theme-text-muted)]">
          No unread tracked issue remains. You can browse previously read issues below.
        </p>
      )}
      <button
        type="button"
        aria-expanded={browseOpen}
        onClick={() => setBrowseOpen((open) => !open)}
        className="min-h-11 rounded-lg px-3 text-sm font-bold text-[var(--theme-primary-action)] hover:underline"
      >
        {browseOpen ? 'Hide issue picker' : 'Choose another owned issue'}
      </button>
      {browseOpen && (
        <div className="space-y-2" data-testid="direct-read-issue-picker">
          {browse.isPending && <p role="status">Loading owned issues…</p>}
          {browse.isError && (
            <p role="alert" className="text-sm text-[var(--theme-danger)]">
              Unable to list issues: {getApiErrorDetail(browse.error)}
              <button type="button" onClick={() => void browse.refetch()} className="ml-2 font-bold underline">
                Retry
              </button>
            </p>
          )}
          <div className="max-h-64 space-y-1 overflow-y-auto" role="group" aria-label="Owned issues">
            {choices.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                onClick={() => {
                  setSelectedIssue(candidate)
                  setBrowseOpen(false)
                }}
                className="block min-h-11 w-full rounded-lg border border-[var(--theme-border)] px-3 text-left text-sm hover:bg-[var(--theme-bg-hover)]"
              >
                {threadTitle} #{candidate.issue_number} ({candidate.status})
              </button>
            ))}
          </div>
          {browse.hasNextPage && (
            <button
              type="button"
              disabled={browse.isFetchingNextPage}
              onClick={() => void browse.fetchNextPage()}
              className="min-h-11 font-bold text-[var(--theme-primary-action)] disabled:opacity-50"
            >
              {browse.isFetchingNextPage ? 'Loading…' : 'Load more issues'}
            </button>
          )}
        </div>
      )}
    </section>
  )
}
