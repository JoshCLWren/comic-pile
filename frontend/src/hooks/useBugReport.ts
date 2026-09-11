import { useCallback, useState } from 'react'
import { bugReportsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { ReportType } from '../components/BugReportModal'
import type { DiagnosticData } from './useDiagnostics'

interface BugReportPayload {
  report_type: ReportType
  title: string
  description: string
  diagnostics?: DiagnosticData
}

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
      // SAFETY: bugReportsApi.create already accepts these fields (diagnostics optional), so the cast narrows to the required subset.
      const createReport = bugReportsApi.create as (data: BugReportPayload) => Promise<{ issue_url: string }>
      const reportPayload: BugReportPayload = { report_type: reportType, title, description }
      if (diagnosticData) {
        reportPayload.diagnostics = diagnosticData
      }
      const response = await createReport(reportPayload)
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
