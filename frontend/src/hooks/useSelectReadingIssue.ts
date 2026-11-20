import { useMutation, useQueryClient } from '@tanstack/react-query'
import { resetRollBootstrapAfterManualSelection } from '../query/cacheEffects'
import { threadsApi } from '../services/api-threads'

/** Select exactly the eligible issue displayed by a Reading Plan or List. */
export function useSelectReadingIssue(threadId: number, issueId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => threadsApi.setPending(threadId, issueId),
    // Roll must fetch the new authoritative pending selection on navigation.
    onSuccess: () => resetRollBootstrapAfterManualSelection(client),
  })
}
