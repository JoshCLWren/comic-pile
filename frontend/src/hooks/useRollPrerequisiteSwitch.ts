import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { fetchAndPublishRollBootstrap, isAmbiguousNetworkFailure } from './rollMutationReconciliation'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { getApiErrorDetail } from '../utils/apiError'

interface RollPrerequisiteSwitchState {
  isPending: boolean
  errorMessage: string | null
  switchIssue: (issueId: number) => Promise<void>
}

export function useRollPrerequisiteSwitch(): RollPrerequisiteSwitchState {
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: async (issueId: number) => {
      setErrorMessage(null)
      try {
        await rollBootstrapApi.switchPrerequisite({ node_type: 'issue', node_id: issueId })
        try {
          await fetchAndPublishRollBootstrap()
        } catch {
          setErrorMessage(
            'The roll switched, but ComicPile could not refresh its recovery guidance. The new reading target may already be active.',
          )
        }
      } catch (error) {
        const ambiguous = isAmbiguousNetworkFailure(error)
        const switchFailure = getApiErrorDetail(error)
        try {
          await fetchAndPublishRollBootstrap()
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
