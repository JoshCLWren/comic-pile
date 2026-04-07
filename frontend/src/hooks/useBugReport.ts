import { useState, useCallback } from 'react'
import { bugReportsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'

export function useBugReport() {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [issueUrl, setIssueUrl] = useState<string | null>(null)

  const submit = useCallback(async (title: string, description: string, screenshotBlob: Blob | null) => {
    setIsSubmitting(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('title', title)
      formData.append('description', description)
      if (screenshotBlob) {
        formData.append('screenshot', screenshotBlob, 'screenshot.png')
      }
      const response = await bugReportsApi.create(formData)
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
