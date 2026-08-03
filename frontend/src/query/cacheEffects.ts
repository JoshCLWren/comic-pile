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
 * Apply the authoritative thread returned by a successful thread edit.
 *
 * Thread edits can change Queue ordering/filter presentation and Roll eligibility,
 * so those screen read models are recalculated narrowly. The returned entity remains
 * authoritative for exact thread detail and summary caches. History, dependencies,
 * analytics, and unrelated thread entries remain valid.
 */
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

/**
 * Reconcile queue ordering mutations without evicting unrelated server state.
 *
 * A move can reshape every filtered or paginated Queue page and can change the
 * current session and Roll selection. Thread details, History, dependencies, and
 * analytics remain valid and must not be globally invalidated.
 */
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
