import { useQuery } from '@tanstack/react-query'
import { collectionsApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'
import type { Collection } from '../types'

export function useCollectionsQuery() {
    return useQuery<Collection[]>({
        queryKey: queryKeys.collections,
        queryFn: async () => {
            const response = await collectionsApi.list()
            return response.collections ?? []
        },
    })
}
