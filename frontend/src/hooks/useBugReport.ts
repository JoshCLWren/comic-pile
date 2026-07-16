import { useState, useCallback } from 'react'
import { bugReportsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { DiagnosticData } from './useDiagnostics'

export function useBugReport() {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [issueUrl, setIssueUrl] = useState<string | null>(null)

  const submit = useCallback(async (
    title: string,
    description: string,
    diagnosticData: DiagnosticData | null,
  ) => {
    setIsSubmitting(true)
    setError(null)
    setIssueUrl(null)
    try {
      const response = await bugReportsApi.create({
        title,
        description,
        ...(diagnosticData ? { diagnostics: diagnosticData } : {}),
      })
      setIssueUrl(response.issue_url)
    } catch (err: unknown) {
      setError(getApiErrorDetail(err) ?? 'Failed to submit bug report')
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
