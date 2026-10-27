import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { threadIssueRoutePath } from '../utils/threadRoutes'
import type { BoundaryEditorTarget, BoundaryIssue, ReadingBoundaryExplanation as Explanation } from '../services/api-reading-boundaries'

/** Translate server-owned rule descriptors into the current editor routes. */
function readingBoundaryEditorHref(editor: BoundaryEditorTarget): string | null {
  if (editor.kind === 'reading_list' && editor.list_id) return `/reading-lists/${editor.list_id}`
  if (editor.kind === 'prerequisite' && editor.thread_id) return `/thread/${editor.thread_id}?prerequisites=1`
  if (editor.thread_id) return threadIssueRoutePath(editor.thread_id, editor.issue_id)
  return null
}

function EditorLink({ editor }: { editor?: BoundaryEditorTarget | null }) {
  const href = editor ? readingBoundaryEditorHref(editor) : null
  return href && editor ? <Link to={href} className="text-[var(--theme-continuity-accent)] underline">Edit {editor.label}</Link> : null
}

function IssueLabel({ issue }: { issue: BoundaryIssue }) {
  return <Link to={threadIssueRoutePath(issue.thread_id, issue.issue_id)} aria-label={`Open ${issue.thread_title} issue #${issue.issue_number}`} className="text-[var(--theme-continuity-accent)] underline">{issue.label}{issue.volume_label && !issue.label.includes(issue.volume_label) ? ` · ${issue.volume_label}` : ''}</Link>
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
  /** Queue-sized presentation: one actionable comic by default, complete reasoning on demand. */
  compact?: boolean
}

const UNAVAILABLE = <p className="text-sm text-[var(--theme-text-muted)]">Reading boundaries are unavailable.</p>

function CompactReadingRequirements({
  primaryIssue,
  editor,
  allRequirements,
}: {
  primaryIssue: BoundaryIssue
  editor?: BoundaryEditorTarget | null
  allRequirements: ReactNode
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <p>Read <IssueLabel issue={primaryIssue} /> first.</p>
      <EditorLink editor={editor} />
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className="min-h-9 text-xs font-semibold text-[var(--theme-continuity-accent)] underline"
      >
        {expanded ? 'Hide' : 'Show'} all reading requirements
      </button>
      {expanded && <div className="mt-2">{allRequirements}</div>}
    </>
  )
}

/** Present the evaluator's result; only current canonical requirements are presented. */
export function ReadingBoundaryExplanation({ explanation, isPending, isError, onRetry, fallback, compact = false }: Props) {
  if (isError) return <div role="alert" className="text-sm text-[var(--theme-error)]"><p>Reading boundaries could not be loaded.</p><button type="button" className="min-h-11 underline" onClick={onRetry}>Retry reading boundaries</button></div>
  if (isPending) return <p role="status" className="text-sm text-[var(--theme-text-muted)]">Loading reading boundaries…</p>
  if (!explanation || explanation.state === 'unavailable') return <>{fallback ?? UNAVAILABLE}</>
  const blockers = explanation.blockers ?? []
  // Strict-list blockers enumerate every earlier unread issue. The first is the
  // actionable reading frontier, while the full set still enforces eligibility.
  const primaryBlocker =
    blockers.find((blocker) => blocker.kind === 'strict_order' && (blocker.waiting_on?.length ?? 0) > 0) ??
    blockers.find((blocker) => (blocker.waiting_on?.length ?? 0) > 0)
  const primaryIssue = primaryBlocker?.waiting_on?.[0]
  const allRequirements = blockers.length > 0 ? (
    <ul className="space-y-2" aria-label="Active reading blockers">
      {blockers.map((blocker, index) => (
        <li key={`${blocker.kind}-${index}`}>
          <p>{blocker.reason}</p>
          <ul className="space-y-1" aria-label="Waiting on comics">
            {blocker.waiting_on?.map((issue) => <li key={issue.issue_id}><IssueLabel issue={issue} /></li>)}
          </ul>
          <EditorLink editor={blocker.editor} />
        </li>
      ))}
    </ul>
  ) : null
  return (
    <div className="min-w-0 space-y-2 break-words text-sm text-[var(--theme-text-muted)]" data-testid="canonical-reading-boundary">
      <p className={`font-semibold ${explanation.state === 'blocked' ? 'text-[var(--theme-warning)]' : 'text-[var(--theme-text-primary)]'}`}>{explanation.summary}</p>
      {explanation.next && <div><p>Next: <IssueLabel issue={explanation.next.issue} /></p><EditorLink editor={explanation.next.editor} /></div>}
      {compact && explanation.state === 'blocked' && primaryIssue ? (
        <CompactReadingRequirements primaryIssue={primaryIssue} editor={primaryBlocker?.editor} allRequirements={allRequirements} />
      ) : allRequirements}
    </div>
  )
}
