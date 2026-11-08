import { useQuery } from '@tanstack/react-query'
import { ComicIssueCard } from '../../components/ComicIssueCard'
import { useIssueCards } from '../../hooks/useIssueCards'
import { issuesApi } from '../../services/api-issues'
import { getApiErrorDetail } from '../../utils/apiError'

interface Props {
  threadId: number
  threadTitle: string
}

/**
 * Resolve an exact owned issue only after the reader opens a Queue row's
 * issue actions. The list projection has a number but no canonical issue ID,
 * so it must never guess an ID or borrow an unrelated issue's cover.
 *
 * One bounded status-filtered read resolves the earliest unread owned issue.
 * The shared card projection then loads only that issue's cover and rating.
 * No per-row request runs for collapsed virtualized Queue rows.
 */
export default function QueueNextIssueCard({ threadId, threadTitle }: Props) {
  const nextQuery = useQuery({
    queryKey: ['queue', 'next-unread-issue', threadId],
    queryFn: async () => {
      const result = await issuesApi.list(threadId, { status: 'unread', page_size: 1 })
      return result.issues[0] ?? null
    },
    retry: false,
  })
  const next = nextQuery.data
  const cardsQuery = useIssueCards(next ? [next.id] : [], { enabled: next != null })
  const card = cardsQuery.data?.find((item) => item.issue_id === next?.id) ?? null

  if (nextQuery.isPending) {
    return <p role="status" className="text-sm text-[var(--theme-text-muted)]">Loading exact issue…</p>
  }

  if (nextQuery.isError) {
    return (
      <div role="alert" className="space-y-2 text-sm text-[var(--theme-danger)]">
        <p>Could not load this series’ unread issues: {getApiErrorDetail(nextQuery.error)}</p>
        <button type="button" onClick={() => void nextQuery.refetch()} className="min-h-11 font-bold underline">
          Retry issue lookup
        </button>
      </div>
    )
  }

  if (!next) {
    return <p role="status" className="text-sm text-[var(--theme-text-muted)]">No tracked unread issues remain for this series.</p>
  }

  return (
    <div className="space-y-2" data-testid="queue-exact-issue-card">
      {cardsQuery.isError && (
        <p role="alert" className="text-xs text-[var(--theme-danger)]">
          Cover and rating details are unavailable: {getApiErrorDetail(cardsQuery.error)}
          <button type="button" onClick={() => void cardsQuery.refetch()} className="ml-2 min-h-9 font-bold underline">
            Retry details
          </button>
        </p>
      )}
      <ComicIssueCard
        issueId={next.id}
        card={card}
        threadTitle={threadTitle}
        issueNumber={String(next.issue_number)}
        status={next.status}
        variant="compact"
        onMutated={() => void nextQuery.refetch()}
      />
      <p className="text-xs text-[var(--theme-text-muted)]">
        Direct reading does not change the pending Roll, die, or Queue position.
      </p>
    </div>
  )
}
