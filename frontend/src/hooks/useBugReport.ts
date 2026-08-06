import { useCallback, useState } from 'react'
import { bugReportsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { ReportType } from '../components/BugReportModal'
import type { DiagnosticData } from './useDiagnostics'

export function useBugReport() {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [issueUrl, setIssueUrl] = useState<string | null>(null)

  const submit = useCallback(async (
    reportType: ReportType,
    title: string,
    description: string,
    diagnosticData: DiagnosticData | null,
  ) => {
    setIsSubmitting(true)
    setError(null)
    setIssueUrl(null)
    try {
      const createReport = bugReportsApi.create as (data: {
        report_type: ReportType
        title: string
        description: string
        diagnostics?: DiagnosticData
      }) => Promise<{ issue_url: string }>
      const response = await createReport({
        report_type: reportType,
        title,
        description,
        ...(diagnosticData ? { diagnostics: diagnosticData } : {}),
      })
      setIssueUrl(response.issue_url)
    } catch (err: unknown) {
      setError(getApiErrorDetail(err) ?? 'Failed to submit report')
      throw err
    } finally {
      setIsSubmitting(false)
    }
  }, [])

  const reset = useCallback(() => {
    setError(null)
    setIssueUrl(null)
  }, [])

  return { isSubmitting, error, issueUrl, submit, reset }
}
