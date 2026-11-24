import { useEffect, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { ComicIssueCard } from './ComicIssueCard'
import { ComicIdentity } from '../pages/RollPage/components/ComicIdentity'
import { TagSection } from './Tags/TagSection'
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
  /** Counter-based legacy series can have unread comics but no Issue rows. */
  issuesRemaining?: number | null
  onMigrate?: () => void
}

/**
 * Exact-owned-issue manual reading, shared by Queue and Roll.
 *
 * Opening this panel and choosing an issue perform only authenticated reads.
 * Neither the next-unread lookup nor the optional all-issues picker checks
 * automatic Roll eligibility. ComicIssueCard Save writes through the
 * owner-scoped, idempotent Rust v2 direct command, which never creates or
 * consumes a pending random Roll offer. The reused provider and tag detail
 * components retain their own explicit edit actions; none run on open.
 *
 * The selected issue opens the same provider details a completed roll shows
 * (cover, summary, creators with roles, story arcs) plus that exact issue's
 * tags, so mappings and credits can be inspected without rolling first (#5751).
 */
export function DirectReadIssuePanel({
  threadId,
  threadTitle,
  preferredIssueId,
  issuesRemaining,
  onMigrate,
}: DirectReadIssuePanelProps) {
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null)
  const [browseOpen, setBrowseOpen] = useState(false)

  const nextUnread = useQuery({
    queryKey: queryKeys.thread.nextUnreadIssue(threadId),
    queryFn: async () => {
      const response = await issuesApi.list(threadId, { status: 'unread', page_size: 1 })
      return response.issues[0] ?? null
    },
    enabled: preferredIssueId == null,
    retry: false,
  })
  const preferredIssue = useQuery({
    queryKey: queryKeys.thread.manualIssue(preferredIssueId ?? 0),
    queryFn: () => {
      if (preferredIssueId == null) throw new Error('An exact issue ID is required')
      return issuesApi.get(preferredIssueId)
    },
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
    // SAFETY: the issue cursor is a nullable string; the first page has no cursor.
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
  // A previously read issue's rating is only available in the authoritative
  // card projection. Opening Edit rating before that fetch resolves would
  // default to 3.5 and silently overwrite a saved rating. Unread issue cards
  // remain usable when optional metadata/cover lookups fail.
  const canShowEditor = issue?.status !== 'read' || card != null
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
          {!canShowEditor && (
            <p role="status" className="text-sm text-[var(--theme-text-muted)]">
              {cards.isFetching
                ? 'Loading the saved rating before editing…'
                : 'Saved rating details are unavailable. Retry details before editing.'}
            </p>
          )}
          <div className="space-y-4" data-testid="direct-read-comic-details">
            {/* Roll parity (#5751): provider details and tags are independent
                of the saved-rating projection, so a card failure cannot hide
                the creators or tags the reader opened this panel to inspect. */}
            <ComicIdentity issueId={issue.id} />
            <div className="min-w-0" data-testid="direct-read-issue-tags">
              <TagSection
                targetType="Issue"
                targetId={issue.id}
                targetLabel={`${threadTitle} #${issue.issue_number}`}
              />
            </div>
            {canShowEditor && (
              <ComicIssueCard
                key={issue.id}
                issueId={issue.id}
                card={card}
                threadTitle={threadTitle}
                issueNumber={String(issue.issue_number)}
                status={issue.status}
                variant="compact"
                showCover={false}
              />
            )}
          </div>
        </>
      )}
      {!lookup.isPending && !lookup.isError && !issue && (
        onMigrate && (issuesRemaining == null || issuesRemaining > 0) ? (
          <div role="status" className="space-y-2 text-sm text-[var(--theme-text-muted)]">
            <p>
              {issuesRemaining != null
                ? `This series has ${issuesRemaining} unread ${issuesRemaining === 1 ? 'comic' : 'comics'} but no individually tracked unread issue.`
                : 'No unread issue is individually tracked for this series.'}
              {' '}Set up issue tracking to read it directly.
            </p>
            <button
              type="button"
              onClick={() => onMigrate()}
              className="min-h-11 rounded-lg px-3 font-bold text-[var(--theme-primary-action)] hover:underline"
            >
              Set up issue tracking
            </button>
          </div>
        ) : (
          <p role="status" className="text-sm text-[var(--theme-text-muted)]">
            No unread tracked issue remains. You can browse previously read issues below.
          </p>
        )
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
