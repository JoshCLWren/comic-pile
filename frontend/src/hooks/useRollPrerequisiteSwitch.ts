import { useContext, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AuthContext } from '../contexts/AuthContext'
import { fetchAndPublishRollState, isAmbiguousNetworkFailure } from './rollMutationReconciliation'
import { rollStateApi } from '../services/rollStateApi'
import { useRollPendingSelection } from './useRollPendingSelection'
import { getApiErrorDetail } from '../utils/apiError'

interface RollPrerequisiteSwitchState {
  isPending: boolean
  errorMessage: string | null
  switchIssue: (issueId: number) => Promise<void>
}

export function useRollPrerequisiteSwitch(): RollPrerequisiteSwitchState {
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const userId = useContext(AuthContext)?.user?.id ?? null
  const { select } = useRollPendingSelection()

  const mutation = useMutation({
    mutationFn: async (issueId: number) => {
      setErrorMessage(null)
      try {
        const response = await rollStateApi.switchPrerequisite({ node_type: 'issue', node_id: issueId })
        select({
          issue_id: response.target_issue_id,
          thread_id: response.target_thread_id,
          issue_number: response.target_issue_number,
        })
        try {
          await fetchAndPublishRollState(rollStateApi, userId)
        } catch {
          setErrorMessage(
            'The roll switched, but ComicPile could not refresh its recovery guidance. The new reading target may already be active.',
          )
        }
      } catch (error) {
        const ambiguous = isAmbiguousNetworkFailure(error)
        const switchFailure = getApiErrorDetail(error)
        try {
          await fetchAndPublishRollState(rollStateApi, userId)
          setErrorMessage(
            ambiguous
              ? 'ComicPile could not confirm whether the roll switched. Recovery guidance has been refreshed.'
              : `${switchFailure}. Recovery guidance has been refreshed.`,
          )
        } catch {
          setErrorMessage(
            ambiguous
              ? 'ComicPile could not confirm whether the roll switched or refresh recovery guidance. Check the current Roll before trying again.'
              : `${switchFailure}. ComicPile also could not refresh recovery guidance.`,
          )
        }
      }
    },
  })

  return {
    isPending: mutation.isPending,
    errorMessage,
    switchIssue: (issueId: number) => mutation.mutateAsync(issueId),
  }
}
