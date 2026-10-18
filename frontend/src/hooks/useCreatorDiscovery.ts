import { useQuery } from '@tanstack/react-query'
import {
  creatorsApi,
  type DiscoveryParams,
} from '../services/api-creators'
import { queryKeys } from '../query/queryKeys'

/**
 * Hook for getting available creator discovery modes (issue #3093).
 *
 * Discovery modes surface useful patterns in user's creator ratings that they
 * may not think to search for manually, while keeping every result deterministic
 * and explainable.
 */
export function useDiscoveryModes() {
  return useQuery({
    queryKey: queryKeys.creators.discovery.modes(),
    queryFn: () => creatorsApi.getDiscoveryModes(),
  })
}

/**
 * Hook for getting creator discovery results for a specific mode (issue #3093).
 *
 * Each discovery mode uses explicit, deterministic calculations with clear
 * minimum sample requirements to ensure statistical validity.
 */
export function useDiscovery(
  params: DiscoveryParams,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: queryKeys.creators.discovery.detail(params.mode, params.limit, params.offset),
    queryFn: () => creatorsApi.getDiscovery(params),
    enabled: enabled && !!params.mode,
  })
}
