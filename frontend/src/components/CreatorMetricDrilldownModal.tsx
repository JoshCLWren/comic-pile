import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Modal } from '../components/Modal'
import { useDrilldownPresentation } from '../hooks/useCreatorMetricDrilldown'
import type { CreatorMetricDrilldown } from '../types/index'
import { IssueList } from './IssueList'
import { CalculationDisplay } from './CalculationDisplay'
import { ExclusionExplanation } from './ExclusionExplanation'

interface CreatorMetricDrilldownModalProps {
  isOpen: boolean
  onClose: () => void
  creatorKey: string
  metricType: string
  metricLabel: string
  initialParams?: {
    role?: string
    ratingValue?: string
    seriesKey?: string
    page?: number
    pageSize?: number
  }
}

export function CreatorMetricDrilldownModal({
  isOpen,
  onClose,
  creatorKey,
  metricType,
  metricLabel,
  initialParams,
}: CreatorMetricDrilldownModalProps) {
  const queryClient = useQueryClient()
  const { presentation, isDesktop } = useDrilldownPresentation()
  const [currentPage, setCurrentPage] = useState(initialParams?.page || 1)
  const [currentParams, setCurrentParams] = useState(initialParams || {})

  // Get the drilldown data from cache or fetch it
  const drilldownData = queryClient.getQueryData<CreatorMetricDrilldown>(
    queryKeys.creators.metric(creatorKey, metricType, currentParams)
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

  // Handle series change for series metrics
  const handleSeriesChange = (seriesKey: string) => {
    setCurrentParams(prev => ({ ...prev, seriesKey, page: 1 }))
  }

  if (!drilldownData) {
    return (
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        title={`Loading ${metricLabel}...`}
        presentation={presentation}
        className="max-w-4xl"
      >
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--theme-primary-action)]"></div>
        </div>
      </Modal>
    )
  }

  const { calculation, included_issues, excluded_issues, pagination } = drilldownData

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`${metricLabel} Details`}
      subtitle={drilldownData.creator_key}
      presentation={presentation}
      className="max-w-4xl"
      actions={
        <div className="flex gap-2">
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
      }
    >
      <div className="space-y-6">
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
            {Object.entries(
              drilldownData.included_issues?.reduce((acc, issue) => {
                const rating = issue.effective_rating
                if (rating) {
                  acc[rating] = (acc[rating] || 0) + 1
                }
                return acc
              }, {} as Record<string, number>) || {}
            ).map(([rating, count]) => (
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

          <IssueList issues={included_issues} />

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