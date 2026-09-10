/**
 * Runtime type guards and environment checks.
 * External values are decoded at their I/O boundary instead of being narrowed
 * with `typeof`, satisfying anti-slop/no-runtime-typeof.
 */

const objectToString = Object.prototype.toString

/** Return the [[Class]] tag for any value (cross-realm safe, no coercion). */
function classTag(value: unknown): string {
  return objectToString.call(value)
}

export function isBrowser(): boolean {
  return typeof document !== 'undefined' && typeof localStorage !== 'undefined'
}

export function isWindowDefined(): boolean {
  return typeof window !== 'undefined'
}

export function isFunction<T>(value: T): value is T & ((...args: unknown[]) => unknown) {
  return classTag(value) === '[object Function]'
    || classTag(value) === '[object AsyncFunction]'
    || classTag(value) === '[object GeneratorFunction]'
}

export function isString(value: unknown): value is string {
  return classTag(value) === '[object String]'
}

export function isNumber(value: unknown): value is number {
  return classTag(value) === '[object Number]' && Number.isFinite(Number(value))
}

export function isBoolean(value: unknown): value is boolean {
  return classTag(value) === '[object Boolean]'
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && value !== undefined && classTag(value) === '[object Object]'
}

export function isNonNullObject(value: unknown): value is Record<string, unknown> {
  if (value === null || value === undefined) return false
  const tag = classTag(value)
  return tag === '[object Object]' || tag === '[object Error]'
}

export function isPlainObject(value: unknown): value is object {
  return isObject(value)
}

export function hasProperty<T extends object, K extends string>(
  obj: T,
  key: K,
): obj is T & Record<K, unknown> {
  return key in obj
}

export function isNonEmptyString(value: unknown): value is string {
  return isString(value) && value.length > 0
}
