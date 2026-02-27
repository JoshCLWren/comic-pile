/**
 * Parse issue range string and return count.
 * Simple client-side version for preview.
 *
 * Supports formats:
 * - "1-25" -> count = 25
 * - "1, 3, 5-7" -> count = 5 (issues 1, 3, 5, 6, 7)
 * - "25" -> count = 1 (single issue number)
 *
 * Annuals/specials should be SEPARATE THREADS with dependencies (not part of main series issue list).
 * This parser only handles numeric issues.
 *
 * @param input - Issue range string (e.g., "1-25" or "1, 3, 5-7")
 * @returns Total number of issues in the range
 * @throws Error if input is invalid
 */
export function parseIssueRange(input: string): number {
  if (!input || !input.trim()) {
    throw new Error('Issue range cannot be empty');
  }

  const trimmedInput = input.trim();

  // Check for non-numeric characters (only allow digits, commas, dashes, spaces)
  if (/[^\d,\-\s]/.test(trimmedInput)) {
    throw new Error(
      'Non-numeric issues detected. Annuals and specials should be created as separate threads.'
    );
  }

  const result: number[] = [];
  const parts = trimmedInput.split(',');

  for (const part of parts) {
    const trimmedPart = part.trim();
    if (!trimmedPart) {
      continue;
    }

    if (trimmedPart.includes('-')) {
      const rangeParts = trimmedPart.split('-');
      if (rangeParts.length !== 2) {
        throw new Error(`Invalid range format: ${trimmedPart}`);
      }

      const startStr = rangeParts[0].trim();
      const endStr = rangeParts[1].trim();

      const start = parseInt(startStr, 10);
      const end = parseInt(endStr, 10);

      if (isNaN(start) || isNaN(end)) {
        throw new Error(`Invalid issue numbers in range: ${trimmedPart}`);
      }

      if (start < 1 || end < 1) {
        throw new Error('Issue numbers must be positive');
      }

      if (start > end) {
        throw new Error(`Range start (${start}) cannot exceed end (${end})`);
      }

      for (let i = start; i <= end; i++) {
        result.push(i);
      }
    } else {
      const issueNum = parseInt(trimmedPart, 10);

      if (isNaN(issueNum)) {
        throw new Error(`Invalid issue number: ${trimmedPart}`);
      }

      if (issueNum < 1) {
        throw new Error('Issue numbers must be positive');
      }

      result.push(issueNum);
    }
  }

  // Deduplicate while preserving order
  const seen = new Set<number>();
  const uniqueResult: number[] = [];

  for (const issue of result) {
    if (!seen.has(issue)) {
      seen.add(issue);
      uniqueResult.push(issue);
    }
  }

  return uniqueResult.length;
}
