import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { rollUtilityActionClass } from '../actionClasses'
import { useUndo } from '../../../hooks/useUndo'
import { queryKeys } from '../../../query/queryKeys'

/** The just-rated comic reference offered on the post-rate copy prompt. */
export interface PostRateReference {
  title: string
  issueNumber: string
  rating: number
}

interface PostRateCopyPromptProps {
  reference: PostRateReference | null
  onDismiss: () => void
  onUndo?: () => void
  canUndo?: boolean
}

/**
 * Dismissible post-rate recovery affordance for external reviews. After a
 * successful rating the reader lands back on the die view, so this prompt
 * surfaces the exact series title + issue string the pre-rate Copy title
 * control would have offered before Mark Read & Save. It never blocks the
 * next roll and follows the pre-rate clipboard feedback pattern.
 */
export function PostRateCopyPrompt({ reference, onDismiss, onUndo, canUndo = false }: PostRateCopyPromptProps) {
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const queryClient = useQueryClient()
  const { mutate: undo, isPending: isUndoPending } = useUndo()

  useEffect(() => {
    setCopyStatus('idle')
  }, [reference])

  if (!reference) return null

  const { title, issueNumber } = reference

  async function handleCopyComicReference() {
    try {
      await navigator.clipboard.writeText(`${title} ${issueNumber}`)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  async function handleUndo() {
    if (onUndo) {
      onUndo()
    }
  }

  return (
    <section
      aria-label="Just rated"
      aria-live="polite"
      data-testid="post-rate-copy-prompt"
      className="mx-auto w-full max-w-xl rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4 shadow-lg"
    >
      <p className="text-sm text-[var(--theme-text-primary)]">
        You just rated{' '}
        <strong className="text-[var(--theme-text-primary)]">
          {title} {issueNumber}
        </strong>{' '}
        a <strong className="text-[var(--theme-personal-accent)]">{reference.rating}/5</strong>.
      </p>
<div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleCopyComicReference}
          className={`min-h-11 ${rollUtilityActionClass(copyStatus)}`}
          aria-label={`Copy ${title} ${issueNumber}`}
          aria-live="polite"
        >
          <svg
            className="h-4 w-4 shrink-0"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H11a3 3 0 0 1 3 3v17a3 3 0 0 0-3-3H6.5A2.5 2.5 0 0 0 4 21.5v-17Z"></path>
            <path d="M20 4.5A2.5 2.5 0 0 0 17.5 2H14"></path>
            <path d="M20 4.5v17A2.5 2.5 0 0 0 17.5 19H14"></path>
          </svg>
          {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Retry copy' : 'Copy title and issue'}
        </button>
        {canUndo && (
          <button
            type="button"
            onClick={handleUndo}
            disabled={isUndoPending}
            className="min-h-11 px-3 bg-white/5 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-widest text-amber-300 hover:bg-white/10 disabled:opacity-60"
            aria-label="Undo this rating"
          >
            {isUndoPending ? 'Undoing...' : 'Undo rating'}
          </button>
        )}
        <p className="text-[10px] font-medium text-[var(--theme-text-dim)]">
          Copies "{title} {issueNumber}"
        </p>
        {copyStatus === 'failed' ? (
          <p className="text-[10px] font-bold text-[var(--theme-danger)]" role="status">
            Copy failed. Use Retry copy to try again.
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="mt-3 rounded-lg px-2 py-1.5 text-xs font-medium text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
        aria-label="Dismiss rating saved notice"
      >
        Dismiss
      </button>
    </section>
  )
}