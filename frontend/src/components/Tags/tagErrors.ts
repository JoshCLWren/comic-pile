import { isNonNullObject, isString } from '../../utils/runtimeChecks'

/**
 * Extract a human-readable message from a failed tag mutation (issue #3032).
 *
 * The API reports failures through the standard `detail` field; anything else
 * falls back to a generic message so the editor never renders `[object Object]`.
 */
export function tagErrorMessage(error: unknown, fallback: string): string {
  if (isNonNullObject(error)) {
    const response = error.response
    if (isNonNullObject(response)) {
      const data = response.data
      if (isNonNullObject(data) && isString(data.detail) && data.detail.trim()) {
        return data.detail
      }
    }
    if (isString(error.message) && error.message.trim()) return error.message
  }
  return fallback
}
