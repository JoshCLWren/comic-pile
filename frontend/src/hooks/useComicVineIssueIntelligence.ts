import { useEffect, useState } from 'react'
import { comicVineApi, type ComicVineIssueIntelligence } from '../services/api'

interface ComicVineIssueIntelligenceState {
  metadata: ComicVineIssueIntelligence | null
  isLoading: boolean
}

export function useComicVineIssueIntelligence(
  issueId: number | null | undefined,
): ComicVineIssueIntelligenceState {
  const [metadata, setMetadata] = useState<ComicVineIssueIntelligence | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let active = true
    setMetadata(null)
    if (!issueId) return () => { active = false }

    setIsLoading(true)
    comicVineApi.getIssueIntelligence(issueId)
      .then((result) => {
        if (active) setMetadata(result)
      })
      .catch(() => {
        if (active) setMetadata(null)
      })
      .finally(() => {
        if (active) setIsLoading(false)
      })

    return () => { active = false }
  }, [issueId])

  return { metadata, isLoading }
}
