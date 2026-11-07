import { useId, useState, type CSSProperties, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ImageWithLoading from './ImageWithLoading'
import ComicIssueMappingAction from './ComicIssueMappingAction'
import { useComicIssueActions } from '../hooks/useComicIssueActions'
import { invalidateIssueCards } from '../query/cacheEffects'
import type { IssueCard, IssueReadRateResponse } from '../services/issueCardsApi'
import type { IssueIdentityResponse } from '../services/api-comicvine'
import { getApiErrorDetail } from '../utils/apiError'

/** Fast-path default for a manual Mark read (#4444); Roll keeps its own 4.0 threshold. */
export const DIRECT_RATING_DEFAULT = 3.5

/** Half-step scale from 0.5 to 5.0 shared by direct and Roll rating controls. */
export const RATING_VALUES = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

/** Responsive presentation variants of one underlying card implementation. */
export type ComicIssueCardVariant = 'compact' | 'standard' | 'featured'

/**
 * The provider CDN image at CSS display dimensions. The `src` is always the
 * exact URL string from the card projection — ComicPile performs no image
 * processing, proxying or rehosting. Compact/standard/featured are layout
 * sizes, not generated images.
 */
export function ComicIssueCover({
  coverImageUrl,
  threadTitle,
  issueNumber,
  variant = 'standard',
}: {
  coverImageUrl: string | null
  threadTitle: string
  issueNumber: string
  variant?: ComicIssueCardVariant
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const hasCover = coverImageUrl != null && coverImageUrl !== '' && failedUrl !== coverImageUrl
  const issueLabel = `${threadTitle} #${issueNumber}`
  const sizeClass =
    variant === 'featured'
      ? 'w-36 sm:w-44'
      : variant === 'compact'
        ? 'w-12'
        : 'w-16 sm:w-20'
  const eager = variant === 'featured'

  return (
    <div
      className={`relative ${sizeClass} shrink-0 overflow-hidden rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-hover)]`}
      style={{ aspectRatio: '2 / 3' }}
      data-testid="comic-issue-cover"
    >
      {hasCover ? (
        <ImageWithLoading
          src={coverImageUrl}
          alt={`Cover for ${issueLabel}`}
          loading={eager ? 'eager' : 'lazy'}
          className="h-full w-full"
          onError={() => setFailedUrl(coverImageUrl)}
        />
      ) : (
        <div
          className="flex h-full w-full flex-col items-center justify-center gap-1 p-1 text-center"
          data-testid="comic-issue-cover-placeholder"
          aria-label={`No cover for ${issueLabel}`}
        >
          <span className="text-[10px] font-black uppercase tracking-wider text-[var(--theme-text-dim)]">
            No cover
          </span>
        </div>
      )}
    </div>
  )
}

/** Canonical identity line: series, exact issue number, read/rating state. */
export function ComicIssueIdentity({
  threadTitle,
  issueNumber,
  status,
  rating,
  variant = 'standard',
}: {
  threadTitle: string
  issueNumber: string
  status: 'read' | 'unread'
  rating: number | null
  variant?: ComicIssueCardVariant
}) {
  const titleClass = variant === 'featured' ? 'text-xl' : 'text-sm'
  return (
    <div className="min-w-0">
      <p className={`break-words font-bold leading-snug text-[var(--theme-text-primary)] ${titleClass}`}>
        {threadTitle} <span className="text-[var(--theme-comic-accent)]">#{issueNumber}</span>
      </p>
      <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
        {status === 'read' ? (
          <>
            <span className="font-semibold text-[var(--theme-success)]">Read</span>
            {rating != null && <span> · Rated {rating}</span>}
          </>
        ) : (
          <span className="font-semibold text-[var(--theme-text-dim)]">Unread</span>
        )}
      </p>
    </div>
  )
}

/** Advisory-only Option E/CBL context. It never gates the manual actions. */
export function ComicIssueAvailability({ advisory }: { advisory: string | null | undefined }) {
  if (!advisory) return null
  return (
    <p className="text-xs italic text-[var(--theme-continuity-accent)]" data-testid="comic-issue-availability">
      {advisory}
    </p>
  )
}

/**
 * Shared 0.5–5.0 rating slider. DecisionCard (Roll) and the manual editor both
 * render this control; the die/queue consequence copy stays in DecisionCard
 * so manual mode never promises Roll-only effects.
 */
export function ComicIssueRatingSlider({
  value,
  onChange,
  disabled = false,
  inputId = 'comic-issue-rating-input',
  valueId = 'comic-issue-rating-value',
  describedBy,
  showScaleNote = true,
  showValue = true,
}: {
  value: number
  onChange: (value: string) => void
  disabled?: boolean
  inputId?: string
  valueId?: string
  /** Overrides the default "value" description for hosts with richer context. */
  describedBy?: string
  showScaleNote?: boolean
  /** Hosts that render their own big rating readout set this to false. */
  showValue?: boolean
}) {
  const fillPct = Math.min(100, Math.max(0, ((value - 0.5) / (5.0 - 0.5)) * 100))
  return (
    <div className="min-w-0 flex-1 space-y-1">
      {showValue && (
        <p className="text-3xl font-black leading-none text-[var(--theme-personal-accent)]" id={valueId}>
          {value.toFixed(1)}
        </p>
      )}
      <input
        type="range"
        id={inputId}
        name="rating"
        min="0.5"
        max="5.0"
        step="0.5"
        value={value}
        disabled={disabled}
        className="rating-slider h-4 w-full disabled:opacity-50"
        // SAFETY: the custom property is read by the slider fill gradient, not by React's CSSProperties
        style={{ '--slider-fill': `${fillPct}%` } as CSSProperties}
        aria-label="Rating from 0.5 to 5.0 in steps of 0.5"
        aria-describedby={describedBy ?? (showValue ? valueId : undefined)}
        onChange={(event) => onChange(event.target.value)}
      />
      {showScaleNote && <p className="text-[11px] text-[var(--theme-text-dim)]">0.5 – 5.0 in half steps</p>}
    </div>
  )
}

export interface ComicIssueCardProps {
  /** Canonical owned issue id — every surface of this card refers to it. */
  issueId: number
  /** Batched owner-scoped projection; enriches cover/rating/mapping when present. */
  card?: IssueCard | null
  /** Fallbacks from the owning list/thread payload while the batch loads. */
  threadTitle: string
  issueNumber: string
  status: 'read' | 'unread'
  rating?: number | null
  variant?: ComicIssueCardVariant
  /** Non-blocking reading-order note ("Normally follows B.P.R.D."). */
  advisory?: string | null
  /** Extra row-local slot (tags, credits, gate widgets) preserved by callers. */
  children?: ReactNode
  /** Notified after a committed mutation so parents can reconcile snapshots. */
  onMutated?: (response: IssueReadRateResponse) => void
  /** Hide the mapping control (provider-only entries use Add to ComicPile instead). */
  showMapping?: boolean
  /** Opens the Add-to-ComicPile flow for provider-only entries. */
  onAddToLibrary?: () => void
  isOwned?: boolean
}

function buildIdentity(card: IssueCard | null | undefined, threadTitle: string): IssueIdentityResponse | undefined {
  if (!card) return undefined
  const state = card.mapping_state.trim().toLowerCase()
  return {
    issue_id: card.issue_id,
    thread_id: card.thread_id,
    thread_title: card.thread_title || threadTitle,
    has_confirmed_identity: card.has_confirmed_identity,
    comicvine_issue_id: card.comicvine_issue_id ?? null,
    confirmed_mappings: [],
    candidate_mappings: [],
    has_unresolved: !card.has_confirmed_identity && state !== 'unmapped' && state !== 'none',
  }
}

/**
 * The single issue-centered card family for direct reading (#4444).
 *
 * Read now, Rate / Mark read, Edit rating and Mark unread act on this exact
 * issue through the shared `useComicIssueActions` write path. The actions are
 * never disabled by availability, blocked, hold, inactive, excluded, later or
 * queue membership. Opening the editor writes nothing; Save commits one direct
 * write with no die/queue effects. The mapping control (#4450) is composed
 * when `showMapping` so an unmapped issue stays readable.
 */
export function ComicIssueCard({
  issueId,
  card,
  threadTitle,
  issueNumber,
  status,
  rating,
  variant = 'standard',
  advisory,
  children,
  onMutated,
  showMapping = true,
  onAddToLibrary,
  isOwned = true,
}: ComicIssueCardProps) {
  const queryClient = useQueryClient()
  const ratingControlId = useId()
  const actions = useComicIssueActions(issueId, { onMutated })
  const [editor, setEditor] = useState<{ mode: 'read' | 'edit'; draftRating: number } | null>(null)

  const resolvedTitle = card?.thread_title || threadTitle
  const resolvedNumber = card?.issue_number || issueNumber
  const resolvedStatus = (card?.status ?? status) === 'read' ? 'read' : 'unread'
  const resolvedRating = card?.rating ?? rating ?? null
  const coverImageUrl = card?.cover_image_url ?? null
  const issueLabel = `${resolvedTitle} #${resolvedNumber}`

  function openEditor(mode: 'read' | 'edit') {
    actions.reset()
    setEditor({ mode, draftRating: resolvedRating ?? DIRECT_RATING_DEFAULT })
  }

  async function handleSave() {
    if (!editor || actions.isPending) return
    try {
      if (editor.mode === 'edit') {
        await actions.updateRating(editor.draftRating)
      } else {
        await actions.markReadAndRate(editor.draftRating)
      }
      setEditor(null)
    } catch {
      // The mutation owns the error state; the editor stays open with Retry.
    }
  }

  async function handleMarkUnread() {
    if (actions.isPending) return
    try {
      await actions.markUnread()
    } catch {
      // Error renders below.
    }
  }

  const primaryClass =
    'inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-black transition-colors hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50'
  const secondaryClass =
    'inline-flex min-h-11 items-center justify-center rounded-lg px-3 text-sm font-bold text-[var(--theme-primary-action)] transition-colors hover:underline disabled:opacity-50'

  const identityForMapping = buildIdentity(card, resolvedTitle)
  const horizontal = variant !== 'featured'

  return (
    <article
      className={`surface-panel rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 ${horizontal ? '' : 'space-y-3'}`}
      aria-label={`Issue ${issueLabel}`}
      data-testid="comic-issue-card"
      data-variant={variant}
    >
      <div className={horizontal ? 'flex items-start gap-3' : ''}>
        <div className={horizontal ? 'flex min-w-0 flex-1 items-start gap-3' : 'flex items-start gap-3'}>
          <ComicIssueCover
            coverImageUrl={coverImageUrl}
            threadTitle={resolvedTitle}
            issueNumber={resolvedNumber}
            variant={variant}
          />
          <div className="min-w-0 flex-1 space-y-1">
            <ComicIssueIdentity
              threadTitle={resolvedTitle}
              issueNumber={resolvedNumber}
              status={resolvedStatus}
              rating={resolvedRating}
              variant={variant}
            />
            <ComicIssueAvailability advisory={advisory} />
            {children}
          </div>
        </div>
      </div>

      {!editor ? (
        <div className="mt-2 flex flex-wrap items-start gap-1" data-testid="comic-issue-actions">
          {!isOwned ? null : resolvedStatus !== 'read' ? (
            <>
              <button
                type="button"
                onClick={() => openEditor('read')}
                disabled={actions.isPending}
                className={primaryClass}
              >
                Read now
              </button>
              <button
                type="button"
                onClick={() => openEditor('read')}
                disabled={actions.isPending}
                className={secondaryClass}
              >
                Rate / Mark read
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => openEditor('edit')}
                disabled={actions.isPending}
                className={secondaryClass}
              >
                Edit rating
              </button>
              <button
                type="button"
                onClick={() => void handleMarkUnread()}
                disabled={actions.isPending}
                className={secondaryClass}
              >
                {actions.isPending ? 'Saving…' : 'Mark unread'}
              </button>
            </>
          )}
          {showMapping && (
            <ComicIssueMappingAction
              issueId={isOwned ? issueId : null}
              threadTitle={resolvedTitle}
              issueNumber={resolvedNumber}
              initialIdentity={identityForMapping}
              fetchEnabled={card != null}
              isOwned={isOwned}
              compact={variant === 'compact'}
              onAddToLibrary={onAddToLibrary}
              onMapped={() => invalidateIssueCards(queryClient)}
            />
          )}
        </div>
      ) : (
        <div className="mt-2 space-y-2 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-hover)] p-3" data-testid="comic-issue-rating-editor">
          <p className="text-sm font-bold text-[var(--theme-text-primary)]">
            {editor.mode === 'edit' ? `Edit rating for ${issueLabel}` : `Rate ${issueLabel}`}
          </p>
          <div className="flex items-center gap-3">
            <ComicIssueRatingSlider
              inputId={`${ratingControlId}-input`}
              valueId={`${ratingControlId}-value`}
              value={editor.draftRating}
              onChange={(raw) => {
                const draftRating = Number(raw)
                setEditor((current) => (current ? { ...current, draftRating } : current))
              }}
              disabled={actions.isPending}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={actions.isPending}
              className={primaryClass}
            >
              {actions.isPending ? 'Saving…' : editor.mode === 'edit' ? 'Save rating' : 'Mark read & save'}
            </button>
            <button
              type="button"
              onClick={() => setEditor(null)}
              disabled={actions.isPending}
              className="inline-flex min-h-11 items-center justify-center rounded-lg border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
          <p className="text-xs text-[var(--theme-text-dim)]">Direct read only — no die or queue change.</p>
        </div>
      )}

      {actions.isError && (
        <p role="alert" className="mt-2 text-sm text-[var(--theme-error)]">
          {getApiErrorDetail(actions.error) || 'Could not save. Your rating was not recorded — try again.'}
          <button
            type="button"
            onClick={() => (editor ? void handleSave() : void handleMarkUnread())}
            className="ml-2 font-bold underline"
          >
            Retry
          </button>
        </p>
      )}
    </article>
  )
}
