import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { customCBLApi } from '../services/api-custom-cbl'
import { queryKeys } from '../query/queryKeys'
import { EligibilityExplanation } from './EligibilityExplanation'
import { ReaderIssueActions } from './ReaderIssueActions'

const AVAILABILITY = {
  read: 'Read', available: 'Available now', blocked: 'Waiting', later: 'After earlier unread issues in this series',
  excluded: 'Excluded from your collection', inactive: 'Series is inactive', legacy: 'Open series for current availability',
}

/** Current authored membership, never the shorter historical plan copy. */
export function ReadingListReader({ listId }: { listId: number }) {
  const query = useQuery({
    queryKey: queryKeys.customCBLs.reader(listId),
    queryFn: () => customCBLApi.getReader(listId),
  })
  if (query.isPending) return <p>Loading Reading List…</p>
  if (query.isError) return <div role="alert"><p>Unable to load this Reading List.</p><button type="button" onClick={() => void query.refetch()}>Retry list</button></div>
  const view = query.data
  return <section aria-label={`Read ${view.name}`} className="space-y-3">
    <h4 className="text-base font-bold text-[var(--theme-text-primary)]">{view.name} · {view.mode === 'strict' ? 'Strict order' : 'Loose order'}</h4>
    {view.execution_mode === 'legacy' && <p className="text-sm text-[var(--theme-text-muted)]">Reading List execution is not active yet. Saved modes and gates do not change current Roll availability.</p>}
    {(view.entries ?? []).length === 0 ? <p>This Reading List is empty.</p> : <ol className="space-y-2">
      {(view.entries ?? []).map((entry) => <li key={entry.issue_id} className="surface-panel rounded-xl p-3">
        <Link to={`/thread/${entry.thread_id}`} className="text-sm font-semibold text-[var(--theme-text-primary)]">{entry.series_name} #{entry.issue_number}</Link>
        {entry.skipped && <p className="text-xs text-[var(--theme-text-muted)]">Skipped only in this list; other lists and Roll may still offer it.</p>}
        <EligibilityExplanation isBlocked={entry.availability === 'blocked'} emptyLabel={AVAILABILITY[entry.availability]} reasons={entry.explanation?.blocking_reasons} dependencies={entry.explanation?.blocking_dependencies} />
        <ReaderIssueActions issueId={entry.issue_id} threadId={entry.thread_id} issueNumber={entry.issue_number} isRead={entry.status === 'read'} available={entry.availability === 'available'} />
      </li>)}
    </ol>}
  </section>
}
