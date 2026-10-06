/**
 * Stable hook for a queue row's "Series actions" trigger button.
 *
 * The Queue list resets its paginated cache after every queue mutation
 * (`invalidateAfterQueueMovement` calls `resetQueries` so pre-mutation cursors
 * cannot duplicate or skip rows). The reset empties the query, so the page
 * briefly unmounts the whole list and remounts it with the refetched rows.
 * A trigger reference held by the card that opened the menu is therefore dead
 * by the time the action settles, and a focus call made at activation time
 * leaves focus on `document.body` (issue #3147).
 *
 * Resolving the trigger by its thread id after the mutation settles targets
 * the same control by identity instead of by element instance, so the restore
 * survives the remount and lands on the invoking control's new row position.
 */
export const SERIES_ACTIONS_TRIGGER_ATTRIBUTE = 'data-series-actions-trigger'

/**
 * Focuses the "Series actions" trigger for a thread once the list has painted
 * its refetched rows.
 *
 * @param threadId - Thread whose Series actions trigger should own focus.
 * @returns True when the trigger was found and focused.
 */
export function focusSeriesActionsTrigger(threadId: number): boolean {
  const selector = `[${SERIES_ACTIONS_TRIGGER_ATTRIBUTE}="${threadId}"]`
  const trigger = document.querySelector<HTMLButtonElement>(selector)
  if (!trigger) return false
  trigger.focus()
  return true
}
