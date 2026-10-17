import { useReaderProgress } from '../hooks/useReaderProgress'
import { useThreadIssuesEffectiveTags } from '../hooks/useTags'
import { IssueTagRowChips } from './Tags/IssueTagRowChips'

/** Reuse the Thread tag presentation and global read-state mutation. */
export function ReaderIssueActions({ issueId, threadId, issueNumber, isRead, available }: {
  issueId: number; threadId: number; issueNumber: string; isRead: boolean; available: boolean
}) {
  const progress = useReaderProgress(issueId, isRead)
  const tags = useThreadIssuesEffectiveTags(threadId)
  const row = tags.data?.issues.find((item) => item.target_id === issueId)
  return (
    <div className="mt-2 space-y-1">
      {row && <IssueTagRowChips data={row} issueNumber={issueNumber} />}
      {tags.isError && <p className="text-xs text-[var(--theme-text-muted)]">Tags unavailable.</p>}
      {(isRead || available) && <button type="button" onClick={() => progress.mutate()} disabled={progress.isPending} className="min-h-11 rounded-lg px-3 text-sm font-semibold text-[var(--theme-primary-action)] disabled:opacity-50">
        {progress.isPending ? 'Saving…' : isRead ? 'Mark unread' : 'Mark read'}
      </button>}
      {progress.isError && <p role="alert" className="text-sm text-[var(--theme-danger)]">Unable to update this issue. Try again.</p>}
    </div>
  )
}
