/**
 * Format a count with the correct singular or plural noun phrase.
 *
 * @param count - The numeric count.
 * @param singular - The noun form used when count is exactly 1.
 * @param plural - The noun form used for all other counts.
 * @returns A phrase like `1 entry` or `2 entries`.
 */
export function countPhraseWithArticle(
  count: number,
  singular: string,
  plural: string,
): string {
  return `${count} ${count === 1 ? singular : plural}`
}