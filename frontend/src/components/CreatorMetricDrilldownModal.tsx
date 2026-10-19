import { useEffect, useState } from 'react'
import Modal from '../components/Modal'
import { useCreatorMetricDrilldown, useDrilldownPresentation } from '../hooks/useCreatorMetricDrilldown'
import { DrilldownIssueList } from './DrilldownIssueList'
import { CalculationDisplay } from './CalculationDisplay'
import { ExclusionExplanation } from './ExclusionExplanation'

interface DrilldownParams {
  role?: string
  ratingValue?: string
  seriesKey?: string
  page?: number
  pageSize?: number
}

interface CreatorMetricDrilldownModalProps {
  isOpen: boolean
  onClose: () => void
  creatorKey: string
  metricType: string
  metricLabel: string
  initialParams?: DrilldownParams
}

export function CreatorMetricDrilldownModal({
  isOpen,
  onClose,
  creatorKey,
  metricType,
  metricLabel,
  initialParams,
}: CreatorMetricDrilldownModalProps) {
  useDrilldownPresentation()
  const [currentPage, setCurrentPage] = useState(initialParams?.page || 1)
  const [currentParams, setCurrentParams] = useState<DrilldownParams>(initialParams || {})

  // Load the evidence for the selected metric. Previously this only read a
  // pre-primed cache entry and never issued a request, so a metric opened a
  // permanent "Loading ..." shell instead of its supporting issues (issue
  // #3460). Fetching here keeps pagination and role/rating filters working
  // because the query key follows `currentParams`.
  const { data: drilldownData, isError } = useCreatorMetricDrilldown(
    creatorKey,
    metricType,
    currentParams,
  )

  // Reset pagination when modal opens
  useEffect(() => {
    if (isOpen) {
      setCurrentPage(initialParams?.page || 1)
      setCurrentParams(initialParams || {})
    }
  }, [isOpen, initialParams])

  // Handle page navigation
  const handlePageChange = (newPage: number) => {
    setCurrentPage(newPage)
    setCurrentParams(prev => ({ ...prev, page: newPage }))
  }

  // Handle role change for role-based metrics
  const handleRoleChange = (role: string) => {
    setCurrentParams(prev => ({ ...prev, role, page: 1 }))
  }

  // Handle rating value change for distribution metrics
  const handleRatingValueChange = (ratingValue: string) => {
    setCurrentParams(prev => ({ ...prev, ratingValue, page: 1 }))
  }

  // A failed fetch must not masquerade as a permanent loading shell: surface
  // the failure so the reader knows the evidence view did not resolve.
  if (isError) {
    return (
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        title={`${metricLabel} Details`}
        size="large"
      >
        <p role="alert" className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          Could not load the evidence for this metric. Close this view and try again.
        </p>
      </Modal>
    )
  }

  if (!drilldownData) {
    return (
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        title={`Loading ${metricLabel}...`}
        size="large"
      >
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--theme-primary-action)]"></div>
        </div>
      </Modal>
    )
  }

  const { calculation, included_issues, excluded_issues, pagination } = drilldownData

  // SAFETY: the accumulator starts as an empty object and only counts numeric ratings, so it is exactly Record<string, number>.
  const ratingBucketCounts: Record<string, number> = included_issues.reduce(
    (acc: Record<string, number>, issue) => {
      const rating = issue.effective_rating
      if (rating) {
        acc[rating] = (acc[rating] || 0) + 1
      }
      return acc
    },
    {},
  )

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`${metricLabel} Details`}
      size="large"
    >
      <div className="space-y-6">
        <div className="flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{
              backgroundColor: 'var(--theme-bg-panel)',
              color: 'var(--theme-text-primary)',
              borderColor: 'var(--theme-border)',
            }}
          >
            Close
          </button>
        </div>
        {/* Calculation Section */}
        <CalculationDisplay calculation={calculation} />

        {/* Metric Type Specific Controls */}
        {metricType === 'role-stats' && (
          <div className="flex flex-wrap gap-2">
            <span className="text-sm font-medium" style={{ color: 'var(--theme-text-muted)' }}>
              Filter by role:
            </span>
            {drilldownData.included_issues?.[0]?.creator_roles?.map((role) => (
              <button
                key={role}
                onClick={() => handleRoleChange(role)}
                className={`px-3 py-1 text-xs rounded-full transition-colors ${
                  currentParams.role === role
                    ? 'bg-[var(--theme-personal-accent)] text-white'
                    : 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] border border-[var(--theme-border)]'
                }`}
              >
                {role}
              </button>
            ))}
          </div>
        )}

        {metricType === 'rating-distribution' && (
          <div className="flex flex-wrap gap-2">
            <span className="text-sm font-medium" style={{ color: 'var(--theme-text-muted)' }}>
              Rating buckets:
            </span>
            {Object.entries(ratingBucketCounts).map(([rating, count]) => (
              <button
                key={rating}
                onClick={() => handleRatingValueChange(rating)}
                className={`px-3 py-1 text-xs rounded-full transition-colors ${
                  currentParams.ratingValue === rating
                    ? 'bg-[var(--theme-personal-accent)] text-white'
                    : 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] border border-[var(--theme-border)]'
                }`}
              >
                {rating}★ ({count})
              </button>
            ))}
          </div>
        )}

        {/* Issues Section */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
              Supporting Issues
            </h3>
            <span className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              {included_issues.length} of {drilldownData.total_count} shown
            </span>
          </div>

          <DrilldownIssueList issues={included_issues} />

          {/* Pagination */}
          {pagination && pagination.total_pages && pagination.total_pages > 1 && (
            <div className="flex items-center justify-between">
              <button
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage <= 1}
                className="px-3 py-1 text-sm rounded-lg disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--theme-bg-panel)',
                  color: 'var(--theme-text-primary)',
                  borderColor: 'var(--theme-border)',
                }}
              >
                Previous
              </button>
              
              <span className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
                Page {currentPage} of {pagination.total_pages}
              </span>
              
              <button
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={!pagination.next_page_token}
                className="px-3 py-1 text-sm rounded-lg disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--theme-bg-panel)',
                  color: 'var(--theme-text-primary)',
                  borderColor: 'var(--theme-border)',
                }}
              >
                Next
              </button>
            </div>
          )}
        </div>

        {/* Exclusion Explanation */}
        {excluded_issues.length > 0 && (
          <ExclusionExplanation
            excludedIssues={excluded_issues}
            totalExcluded={excluded_issues.length}
          />
        )}
      </div>
    </Modal>
  )
}