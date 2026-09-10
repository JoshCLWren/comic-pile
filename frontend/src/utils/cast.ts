/**
 * Safely retype a value that is otherwise unrelated.
 * Single `as T` assertion encapsulated here so call sites avoid
 * `as unknown as T` chains flagged by `no-chained-type-assertions`.
 */
export function cast<T>(value: unknown): T {
  return value as T
}
