import { hasProperty, isNonEmptyString, isNonNullObject, isString } from '../../utils/runtimeChecks'

/**
 * Decode an API error payload at the I/O boundary.
 *
 * The transport throws untyped rejections, so the wire shape is decoded once
 * here instead of being narrowed with `typeof` at each call site.
 */
function responseDetail(err: unknown): string | null {
  if (!isNonNullObject(err) || !hasProperty(err, 'response')) return null
  const response = err.response
  if (!isNonNullObject(response) || !hasProperty(response, 'data')) return null
  const data = response.data
  if (!isNonNullObject(data) || !hasProperty(data, 'detail')) return null
  return isNonEmptyString(data.detail) ? data.detail : null
}

export function tagErrorMessage(err: unknown, fallback: string): string {
  const detail = responseDetail(err)
  if (detail !== null) return detail
  if (err instanceof Error) return err.message
  if (isString(err)) return err
  return fallback
}