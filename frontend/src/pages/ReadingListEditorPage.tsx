import { useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import ContainerQueueActions from '../components/ContainerQueueActions'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { customCBLApi } from '../services/api-custom-cbl'
import { queryKeys } from '../query/queryKeys'

/** Route an owned rule's editor target into the existing Reading List authoring UI. */
export default function ReadingListEditorPage() {
  const { id } = useParams<{ id: string }>()
  const listId = Number(id)
  const valid = Boolean(id && /^\d+$/.test(id) && Number.isSafeInteger(listId) && listId > 0)
  const listQuery = useQuery({
    queryKey: queryKeys.customCBLs.detail(listId),
    queryFn: () => customCBLApi.get(listId),
    enabled: valid,
  })
  const memberThreads = useMemo(() => {
    const entries = listQuery.data?.entries ?? []
    const byId = new Map<number, { id: number; title: string }>()
    for (const entry of entries) {
      if (entry.thread_id > 0 && !byId.has(entry.thread_id)) {
        byId.set(entry.thread_id, { id: entry.thread_id, title: entry.series_name })
      }
    }
    return Array.from(byId.values())
  }, [listQuery.data])

  if (!valid) {
    return <p role="alert">Reading List not found.</p>
  }

  return (
    <div className="space-y-4 p-3 md:p-4">
      <h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Edit Reading List</h1>
      {listQuery.data && (
        <ContainerQueueActions
          sourceKind="reading_list"
          sourceId={listId}
          sourceName={listQuery.data.name}
          memberThreads={memberThreads}
        />
      )}
      <CustomCBLBuilder key={listId} initialListId={listId} lockListSelection />
    </div>
  )
}
