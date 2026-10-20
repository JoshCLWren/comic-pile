/**
 * Keyboard navigation for custom `role="radiogroup"` surfaces.
 *
 * Comic Pile builds radio groups out of `<button role="radio">` elements so the
 * product can control presentation. Those elements do not inherit the native
 * radio-group keyboard contract, so each group has to resolve arrow-key
 * movement itself. This helper implements the WAI-ARIA radio-group movement
 * keys, including wrap-around at both ends and Home/End jumps.
 */

/** Keys that move focus between radio options in a `role="radiogroup"`. */
export const RADIO_GROUP_NAVIGATION_KEYS = [
  'ArrowDown',
  'ArrowRight',
  'ArrowUp',
  'ArrowLeft',
  'Home',
  'End',
] as const

/**
 * Resolve the option index a radio-group navigation key should move to.
 *
 * Args:
 *   key: The `KeyboardEvent.key` value.
 *   focusedIndex: Index of the currently focused option, or -1 when focus is
 *     not on a known option.
 *   optionCount: Number of options rendered in the group.
 *
 * Returns:
 *   The target option index, or `null` when the key is not a radio-group
 *   navigation key or no movement is possible.
 */
export function radioGroupNavigationTarget(
  key: string,
  focusedIndex: number,
  optionCount: number,
): number | null {
  if (optionCount <= 0 || focusedIndex < 0 || focusedIndex >= optionCount) return null

  if (key === 'ArrowDown' || key === 'ArrowRight') {
    return (focusedIndex + 1) % optionCount
  }
  if (key === 'ArrowUp' || key === 'ArrowLeft') {
    return (focusedIndex - 1 + optionCount) % optionCount
  }
  if (key === 'Home') return 0
  if (key === 'End') return optionCount - 1

  return null
}
