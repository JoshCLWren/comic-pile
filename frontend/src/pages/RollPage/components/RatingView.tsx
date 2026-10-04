import { useState } from 'react'
import type { RatingViewData } from '../useRatingView'
import {
  ROLL_WORKSPACE_GUTTER,
  ROLL_WORKSPACE_MAX_WIDTH,
  ROLL_WORKSPACE_TRACKS,
} from '../workspaceLayout'
import { ComicPillar } from './ComicPillar'
import { DecisionCard } from './DecisionCard'
import { ReadingContextCard } from './ReadingContextCard'
import { ReadingBoundariesCard } from './ReadingBoundariesCard'
import { readingContextType } from '../readingContextTypography'

interface RatingViewProps {
  data: RatingViewData
}

export function RatingView({ data }: RatingViewProps) {
  const {
    activeRatingThread,
    currentDie,
    rolledResult: _rolledResult,
    rating,
    predictedDie,
    errorMessage,
    rateIsPending,
    snoozeIsPending,
    dismissIsPending,
    skipIsPending,
    onUpdateRating,
    onSubmitRating,
    onSnooze,
    onSkip,
    onCancel,
    onRefreshThread,
    readerContext,
    isReaderContextLoading,
    readerContextError,
    readingContextRequested,
    readingBoundariesRequested,
    onRequestReadingContext,
    onRequestReadingBoundaries,
    ratingViewTopRef,
  } = data

  const [isReadingContextOpen, setIsReadingContextOpen] = useState(false)
  const [isReadingBoundariesOpen, setIsReadingBoundariesOpen] = useState(false)

  const handleReadingContextToggle = () => {
    setIsReadingContextOpen((prev) => {
      if (!prev) onRequestReadingContext()
      return !prev
    })
  }
  const handleReadingBoundariesToggle = () => {
    setIsReadingBoundariesOpen((prev) => {
      if (!prev) onRequestReadingBoundaries()
      return !prev
    })
  }

  // Loading/error render only after the user requests that card's scope, so
  // collapsed cards never show a skeleton for unrequested data.
  const contextIsLoading = readingContextRequested && isReaderContextLoading
  const boundariesIsLoading = readingBoundariesRequested && isReaderContextLoading
  const readerContextErrorMessage = readerContextError?.message ?? null
  const localIssues = readerContext?.local_chain.issues ?? []
  const seriesName = readerContext?.series.series_name ?? null

  return (
    <div ref={ratingViewTopRef} data-testid="rating-view-top" className="relative z-10 space-y-4 p-3 md:p-4">
      <div
        className={`grid items-start ${ROLL_WORKSPACE_GUTTER} ${ROLL_WORKSPACE_MAX_WIDTH} lg:justify-center ${ROLL_WORKSPACE_TRACKS}`}
        data-testid="rating-pillars-grid"
      >
        <div className="min-w-0" data-testid="rating-region-comic">
          <ComicPillar activeRatingThread={activeRatingThread} onRefreshThread={onRefreshThread} />
        </div>

        <div className="min-w-0 space-y-4 w-full lg:w-auto lg:sticky lg:top-4" data-testid="rating-region-decision">
          <DecisionCard
            activeRatingThread={activeRatingThread}
            currentDie={currentDie}
            rating={rating}
            predictedDie={predictedDie}
            errorMessage={errorMessage}
            rateIsPending={rateIsPending}
            snoozeIsPending={snoozeIsPending}
            dismissIsPending={dismissIsPending}
            skipIsPending={skipIsPending}
            onUpdateRating={onUpdateRating}
            onSubmitRating={onSubmitRating}
            onSnooze={onSnooze}
            onSkip={onSkip}
            onCancel={onCancel}
          />

          {activeRatingThread && (
            <>
              <ReadingContextCard
                isLoading={contextIsLoading}
                error={readerContextErrorMessage}
                isOpen={isReadingContextOpen}
                onToggle={handleReadingContextToggle}
              >
                {readerContext && (
                  <div className="space-y-2 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3">
                    {seriesName && (
                      <div
                        className="font-bold text-[var(--theme-text-primary)]"
                        style={readingContextType('sectionHeading')}
                      >
                        {seriesName}
                      </div>
                    )}
                    {localIssues.length > 0 ? (
                      <ul className="space-y-1">
                        {localIssues.map((issue) => (
                          <li
                            key={issue.issue_id}
                            className="text-[11px] text-stone-400"
                            style={readingContextType('bodyCopy')}
                          >
                            {issue.relation === 'current' ? 'You are here' : issue.relation}
                            {` · #${issue.issue_number}`}
                            {issue.status ? ` · ${issue.status}` : ''}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span
                        className="text-[11px] text-stone-400"
                        style={readingContextType('bodyCopy')}
                      >
                        See how this issue fits into your reading plans and continuity.
                      </span>
                    )}
                  </div>
                )}
              </ReadingContextCard>

              <ReadingBoundariesCard
                isLoading={boundariesIsLoading}
                error={readerContextErrorMessage}
                readerContext={readerContext}
                isOpen={isReadingBoundariesOpen}
                onToggle={handleReadingBoundariesToggle}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
