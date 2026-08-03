import type { QueryClient } from '@tanstack/react-query'
import type { Thread } from '../types'
import { queryKeys } from './queryKeys'

/**
 * Apply the authoritative thread returned by a successful rating mutation.
 *
 * Rating changes the rated thread and current-session state. It must not invalidate
 * every Queue, History, analytics, dependency, or thread-page query.
 */
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

/**
 * Reconcile snooze and unsnooze mutations through their authoritative owner.
 *
 * Snooze membership lives on the current session, so these mutations must not
 * invalidate full thread pages or unrelated screen caches.
 */
export async function invalidateCurrentSessionAfterSnooze(
  client: QueryClient,
): Promise<void> {
  await client.invalidateQueries({
    queryKey: queryKeys.session.current(),
    exact: true,
  })
}
