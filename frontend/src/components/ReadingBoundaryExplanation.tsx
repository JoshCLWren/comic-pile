import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { BoundaryEditorTarget, BoundaryIssue, ReadingBoundaryExplanation as Explanation } from '../services/api-reading-boundaries'

/** Translate server-owned rule descriptors into the current editor routes. */
function readingBoundaryEditorHref(editor: BoundaryEditorTarget): string | null {
  if (editor.kind === 'reading_list' && editor.list_id) return `/reading-lists/${editor.list_id}`
  if (editor.kind === 'prerequisite' && editor.thread_id) return `/thread/${editor.thread_id}?prerequisites=1`
  if (editor.thread_id) return `/thread/${editor.thread_id}${editor.issue_id ? `?issue=${editor.issue_id}#issue-${editor.issue_id}` : ''}`
  return null
}

function EditorLink({ editor }: { editor?: BoundaryEditorTarget | null }) {
  const href = editor ? readingBoundaryEditorHref(editor) : null
  return href && editor ? <Link to={href} className="text-[var(--theme-continuity-accent)] underline">Edit {editor.label}</Link> : null
}

function IssueLabel({ issue }: { issue: BoundaryIssue }) {
  return <Link to={`/thread/${issue.thread_id}?issue=${issue.issue_id}#issue-${issue.issue_id}`} aria-label={`Open ${issue.thread_title} issue #${issue.issue_number}`} className="text-[var(--theme-continuity-accent)] underline">{issue.label}{issue.volume_label && !issue.label.includes(issue.volume_label) ? ` · ${issue.volume_label}` : ''}</Link>
}

interface Props {
  explanation?: Explanation
  isPending?: boolean
  isError?: boolean
  onRetry?: () => void
  /**
   * Legacy availability explanation for deployments where the canonical
   * evaluator is switched off. The endpoint answers `state: "unavailable"` for
   * every series in that mode, so callers supply the server's existing
   * next-issue/blocker detail instead of dropping it.
   */
  fallback?: ReactNode
}

const UNAVAILABLE = <p className="text-sm text-[var(--theme-text-muted)]">Reading boundaries are unavailable.</p>

/** Present the evaluator's result; only current canonical requirements are presented. */
export function ReadingBoundaryExplanation({ explanation, isPending, isError, onRetry, fallback }: Props) {
  if (isError) return <div role="alert" className="text-sm text-[var(--theme-error)]"><p>Reading boundaries could not be loaded.</p><button type="button" className="min-h-11 underline" onClick={onRetry}>Retry reading boundaries</button></div>
  if (isPending) return <p role="status" className="text-sm text-[var(--theme-text-muted)]">Loading reading boundaries…</p>
  if (!explanation || explanation.state === 'unavailable') return <>{fallback ?? UNAVAILABLE}</>
  return (
    <div className="min-w-0 space-y-2 break-words text-sm text-[var(--theme-text-muted)]" data-testid="canonical-reading-boundary">
      <p className={`font-semibold ${explanation.state === 'blocked' ? 'text-[var(--theme-warning)]' : 'text-[var(--theme-text-primary)]'}`}>{explanation.summary}</p>
      {explanation.next && <div><p>Next: <IssueLabel issue={explanation.next.issue} /></p><EditorLink editor={explanation.next.editor} /></div>}
      {(explanation.blockers?.length ?? 0) > 0 && (
        <ul className="space-y-2" aria-label="Active reading blockers">
          {explanation.blockers?.map((blocker, index) => (
            <li key={`${blocker.kind}-${index}`}>
              <p>{blocker.reason}</p>
              <ul className="space-y-1" aria-label="Waiting on comics">
                {blocker.waiting_on?.map((issue) => <li key={issue.issue_id}><IssueLabel issue={issue} /></li>)}
              </ul>
              <EditorLink editor={blocker.editor} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
