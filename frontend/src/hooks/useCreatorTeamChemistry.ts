import { useQuery } from '@tanstack/react-query'
import { creatorTeamChemistryApi } from '../services/creatorTeamChemistryApi'
import { queryKeys } from '../query/queryKeys'
import type { CreatorTeamChemistryResponse } from '../types/index'

export function useCreatorTeamChemistry(enabled = true) {
  const { data, isPending, isError, error, refetch } = useQuery<CreatorTeamChemistryResponse>({
    queryKey: queryKeys.creators.teamChemistry(),
    queryFn: () => creatorTeamChemistryApi.getChemistry(),
    enabled,
    staleTime: 10 * 60 * 1000, // 10 minutes (team chemistry changes less frequently)
    gcTime: 30 * 60 * 1000, // 30 minutes
  })

  return { data, isPending, isError, error, refetch }
}
