import type { QueryClient } from '@tanstack/react-query'
import type { Thread } from '../types'
import { queryKeys } from './queryKeys'

export async function applyRatedThreadCache(client: QueryClient, thread: Thread): Promise<void> {
  client.setQueryData(queryKeys.thread.detail(thread.id), thread)
  client.setQueryData(queryKeys.thread.summary(thread.id), thread)
  await client.invalidateQueries({ queryKey: queryKeys.session.current(), exact: true })
}

export async function applyUpdatedThreadCache(client: QueryClient, thread: Thread): Promise<void> {
  client.setQueryData(queryKeys.thread.detail(thread.id), thread)
  client.setQueryData(queryKeys.thread.summary(thread.id), thread)
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
    client.invalidateQueries({ queryKey: queryKeys.session.current(), exact: true }),
    client.invalidateQueries({ queryKey: queryKeys.roll.bootstrap(), exact: true }),
  ])
}

export async function invalidateCurrentSessionAfterSnooze(client: QueryClient): Promise<void> {
  await client.invalidateQueries({ queryKey: queryKeys.session.current(), exact: true })
}

export async function invalidateAfterQueueMovement(client: QueryClient): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.queue.pages() }),
    client.invalidateQueries({ queryKey: queryKeys.session.current(), exact: true }),
    client.invalidateQueries({ queryKey: queryKeys.roll.bootstrap(), exact: true }),
  ])
}
