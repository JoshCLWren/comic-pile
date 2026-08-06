import type { QueryClient } from '@tanstack/react-query'
import type { Thread } from '../types'
import { queryKeys } from './queryKeys'

export type ThreadCacheRollback = () => void

export function optimisticallyUpdateThreadCache(
  client: QueryClient,
  threadId: number,
  update: (thread: Thread) => Thread,
): ThreadCacheRollback {
  const detailKey = queryKeys.thread.detail(threadId)
  const summaryKey = queryKeys.thread.summary(threadId)
  const previousDetail = client.getQueryData<Thread>(detailKey)
  const previousSummary = client.getQueryData<Thread>(summaryKey)

  if (previousDetail) {
    client.setQueryData(detailKey, update(previousDetail))
  }
  if (previousSummary) {
    client.setQueryData(summaryKey, update(previousSummary))
  }

  return () => {
    if (previousDetail) {
      client.setQueryData(detailKey, previousDetail)
    } else {
      client.removeQueries({ queryKey: detailKey, exact: true })
    }

    if (previousSummary) {
      client.setQueryData(summaryKey, previousSummary)
    } else {
      client.removeQueries({ queryKey: summaryKey, exact: true })
    }
  }
}

export async function applyRatedThreadCache(
  client: QueryClient,
  thread: Thread,
): Promise<void> {
  client.setQueryData(queryKeys.thread.detail(thread.id), thread)
  client.setQueryData(queryKeys.thread.summary(thread.id), thread)

  await client.invalidateQueries({
    queryKey: queryKeys.session.current(),
    exact: true,
  })
}

export async function applyUpdatedThreadCache(
  client: QueryClient,
  thread: Thread,
): Promise<void> {
  client.setQueryData(queryKeys.thread.detail(thread.id), thread)
  client.setQueryData(queryKeys.thread.summary(thread.id), thread)

  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
  ])
}

export async function invalidateAfterIssueEdit(
  client: QueryClient,
  threadId: number,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({
      queryKey: queryKeys.thread.issuePages(threadId),
    }),
    client.invalidateQueries({
      queryKey: queryKeys.thread.detail(threadId),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.thread.summary(threadId),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
  ])
}

export async function invalidateCurrentSessionAfterSnooze(
  client: QueryClient,
): Promise<void> {
  await client.invalidateQueries({
    queryKey: queryKeys.session.current(),
    exact: true,
  })
}

export async function invalidateAfterQueueMovement(
  client: QueryClient,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
    client.invalidateQueries({
      queryKey: queryKeys.session.current(),
      exact: true,
    }),
    client.invalidateQueries({
      queryKey: queryKeys.roll.bootstrap(),
      exact: true,
    }),
  ])
}
