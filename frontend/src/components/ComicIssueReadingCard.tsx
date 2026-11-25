import { useState } from 'react'
import { ComicIssueCard, type ComicIssueCardProps } from './ComicIssueCard'
import { ComicIdentity } from '../pages/RollPage/components/ComicIdentity'
import { TagSection } from './Tags/TagSection'
import { useComicVineIssueIntelligence } from '../hooks/useComicVineIssueIntelligence'

export interface ComicIssueReadingCardProps extends ComicIssueCardProps {
  /** Show details as soon as this on-demand card mounts (for example a reader header). */
  showReadingDetails?: boolean
}

/**
 * The direct issue action card plus the same provider and tag details as Roll.
 *
 * Dense lists keep `showReadingDetails` false, so collapsed rows perform no
 * provider or tag reads. Opening Read now / Rate / Edit rating requests the
 * details for that exact issue; hosts that already represent an opened reader
 * can request them on mount. Once requested, the details stay visible while
 * the reader adjusts mappings or saves a rating.
 */
export function ComicIssueReadingCard({
  showReadingDetails = false,
  showCover = true,
  isOwned = true,
  issueId,
  card,
  threadTitle,
  issueNumber,
  ...cardProps
}: ComicIssueReadingCardProps) {
  const [requestedIssueId, setRequestedIssueId] = useState<number | null>(null)
  const detailsOpen = isOwned && (showReadingDetails || requestedIssueId === issueId)
  const intelligence = useComicVineIssueIntelligence(detailsOpen ? issueId : null)
  // Match DirectReadIssuePanel: keep the local cover only when provider art is
  // absent or failed. React Query deduplicates this read with ComicIdentity.
  const providerCoverVisible =
    detailsOpen && !intelligence.isError && (intelligence.isLoading || intelligence.metadata != null)
  const resolvedTitle = card?.thread_title || threadTitle
  const resolvedNumber = card?.issue_number || issueNumber

  return (
    <div className="min-w-0 space-y-4" data-testid="comic-issue-reading-card">
      {detailsOpen && (
        <div className="min-w-0 space-y-4" data-testid="comic-issue-reading-details">
          <ComicIdentity issueId={issueId} />
          <TagSection
            targetType="Issue"
            targetId={issueId}
            targetLabel={`${resolvedTitle} #${resolvedNumber}`}
          />
        </div>
      )}
      <ComicIssueCard
        key={issueId}
        {...cardProps}
        issueId={issueId}
        card={card}
        threadTitle={threadTitle}
        issueNumber={issueNumber}
        isOwned={isOwned}
        showCover={showCover && !providerCoverVisible}
        onReadingDetailsRequest={() => setRequestedIssueId(issueId)}
      />
    </div>
  )
}
