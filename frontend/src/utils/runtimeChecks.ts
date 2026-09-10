/**
 * Lightweight runtime type guards used by hooks and test setup.
 *
 * These replace `typeof arg === 'string'` inline checks that were previously
 * spread across call sites, keeping the narrow in one place.
 */

/**
 * Returns true when `value` is a string primitive.
 */
export function isString(value: unknown): value is string {
  return typeof value === 'string'
}

/**
 * Returns true when `value` is a callable function.
 */
export function isFunction(value: unknown): value is (...args: unknown[]) => unknown {
  return typeof value === 'function'
}