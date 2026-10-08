/**
 * Maximum number of issues allowed in a single range.
 * Prevents denial-of-service attacks from ranges like "1-999999999" that would
 * exhaust memory and crash the application.
 */
const MAX_ISSUES = 10000;
const MAX_LITERAL_LENGTH = 100;

/**
 * Known comic issue naming patterns that are considered "recognized" literals.
 * These patterns follow common comic book numbering conventions.
 */
const RECOGNIZED_LITERAL_PATTERNS: RegExp[] = [
  /^Annual\s+#?\d+$/i,
  /^Special\s+#?\d+$/i,
  /^½$/,
  /^FCBD\s+\d{4}$/i,
  /^#\d+$/,
  /^Vol\.\s*\d+\s*#\d+$/i,
];

/**
 * Check if a literal issue identifier matches known comic naming conventions.
 */
function isRecognizedLiteral(literal: string): boolean {
  return RECOGNIZED_LITERAL_PATTERNS.some((pattern) => pattern.test(literal));
}

/**
 * Detailed result of parsing an issue range string.
 */
export interface ParsedIssueRangeDetail {
  /** Total number of unique issues */
  total: number;
  /** List of all unique issue identifiers */
  issues: string[];
  /** Warnings for unrecognized literal tokens */
  warnings: string[];
  /** Breakdown of each input token and how it was parsed */
  breakdown: ParsedTokenBreakdown[];
}

/**
 * Breakdown of a single token from the input.
 */
export interface ParsedTokenBreakdown {
  /** The original token from the input (trimmed) */
  token: string;
  /** Type of token */
  type: 'range' | 'number' | 'recognized-literal' | 'unrecognized-literal';
  /** Issues this token expands to */
  parsedIssues: string[];
}

/**
 * Parse issue range string and return detailed breakdown.
 * Simple client-side version for preview.
 *
 * NOTE: The backend has a parallel parser at app/utils/issue_parser.py
 * that must be kept in sync with this logic.
 *
 * Supports formats:
 * - "1-25" -> count = 25
 * - "0-18" -> count = 19 (issues 0..18)
 * - "1, 3, 5-7" -> count = 5 (issues 1, 3, 5, 6, 7)
 * - "0, Annual 1, 5-7" -> count = 5 (issues 0, Annual 1, 5, 6, 7)
 * - "½" -> count = 1
 *
 * Tokens with a dash are attempted as integer ranges (both endpoints >= 0).
 * If that fails, the whole token is kept as a literal identifier.
 *
 * @param input - Issue range string (e.g., "0-25" or "0, Annual 1, 5-7")
 * @returns Detailed parsing result with breakdown and warnings
 * @throws Error if input is invalid
 */
export function parseIssueRangeDetailed(input: string): ParsedIssueRangeDetail {
  if (!input || !input.trim()) {
    throw new Error('Issue range cannot be empty');
  }

  const trimmedInput = input.trim();
  const result: string[] = [];
  const breakdown: ParsedTokenBreakdown[] = [];
  const warnings: string[] = [];
  const parts = trimmedInput.split(',');

  for (const part of parts) {
    const trimmedPart = part.trim();
    if (!trimmedPart) {
      continue;
    }

    if (trimmedPart.includes('-')) {
      // Try to parse as an integer range
      const dashIdx = trimmedPart.indexOf('-');
      const left = trimmedPart.slice(0, dashIdx).trim();
      const right = trimmedPart.slice(dashIdx + 1).trim();

      const start = Number.parseInt(left, 10);
      const end = Number.parseInt(right, 10);

      // Verify entire string is numeric (matches backend int() behavior which rejects partial parses like "5a")
      // Use regex to allow zero-padded numbers while rejecting trailing non-numeric characters
      const isNumeric = (str: string) => /^\d+$/.test(str);
      if (!Number.isNaN(start) && !Number.isNaN(end) && isNumeric(left) && isNumeric(right)) {
        if (start < 0 || end < 0) {
          throw new Error('Range endpoints must be >= 0');
        }
        if (start > end) {
          throw new Error(`Range start (${start}) cannot exceed end (${end})`);
        }
        // Check range size BEFORE expansion to prevent DoS (matches backend check)
        const rangeSize = end - start + 1;
        if (rangeSize > MAX_ISSUES) {
          throw new Error(`Range too large: ${rangeSize} issues (max ${MAX_ISSUES})`);
        }
        // Check cumulative total to prevent combining multiple large ranges
        if (result.length + rangeSize > MAX_ISSUES) {
          throw new Error(`Total issues would exceed maximum of ${MAX_ISSUES}`);
        }
        const parsedIssues: string[] = [];
        for (let i = start; i <= end; i++) {
          const issueStr = String(i);
          parsedIssues.push(issueStr);
          result.push(issueStr);
        }
        breakdown.push({
          token: trimmedPart,
          type: 'range',
          parsedIssues,
        });
      } else {
        // Not a valid integer range — store as literal
        if (trimmedPart.length > MAX_LITERAL_LENGTH) {
          throw new Error(`Issue identifier too long (max ${MAX_LITERAL_LENGTH} chars)`);
        }
        const recognized = isRecognizedLiteral(trimmedPart);
        if (!recognized) {
          warnings.push(`Couldn't parse '${trimmedPart}' — it will be created as a literal issue name`);
        }
        result.push(trimmedPart);
        breakdown.push({
          token: trimmedPart,
          type: recognized ? 'recognized-literal' : 'unrecognized-literal',
          parsedIssues: [trimmedPart],
        });
      }
    } else {
      // Single token — accept any non-empty string
      if (trimmedPart.length > MAX_LITERAL_LENGTH) {
        throw new Error(`Issue identifier too long (max ${MAX_LITERAL_LENGTH} chars)`);
      }
      const isNumber = /^\d+$/.test(trimmedPart);
      let recognized = false;
      if (!isNumber) {
        recognized = isRecognizedLiteral(trimmedPart);
        if (!recognized) {
          warnings.push(`Couldn't parse '${trimmedPart}' — it will be created as a literal issue name`);
        }
      }
      result.push(trimmedPart);
      breakdown.push({
        token: trimmedPart,
        type: isNumber ? 'number' : recognized ? 'recognized-literal' : 'unrecognized-literal',
        parsedIssues: [trimmedPart],
      });
    }
  }

  // Deduplicate while preserving order
  const seen = new Set<string>();
  const uniqueResult: string[] = [];

  for (const issue of result) {
    if (!seen.has(issue)) {
      seen.add(issue);
      uniqueResult.push(issue);
    }
  }

  if (uniqueResult.length > MAX_ISSUES) {
    throw new Error(`Cannot create more than ${MAX_ISSUES} issues at once`);
  }

  return {
    total: uniqueResult.length,
    issues: uniqueResult,
    warnings,
    breakdown,
  };
}

/**
 * Parse issue range string and return count.
 * Simple client-side version for preview.
 *
 * NOTE: The backend has a parallel parser at app/utils/issue_parser.py
 * that must be kept in sync with this logic.
 *
 * Supports formats:
 * - "1-25" -> count = 25
 * - "0-18" -> count = 19 (issues 0..18)
 * - "1, 3, 5-7" -> count = 5 (issues 1, 3, 5, 6, 7)
 * - "0, Annual 1, 5-7" -> count = 5 (issues 0, Annual 1, 5, 6, 7)
 * - "½" -> count = 1
 *
 * Tokens with a dash are attempted as integer ranges (both endpoints >= 0).
 * If that fails, the whole token is kept as a literal identifier.
 *
 * @param input - Issue range string (e.g., "0-25" or "0, Annual 1, 5-7")
 * @returns Total number of issues in the range
 * @throws Error if input is invalid
 */
export function parseIssueRange(input: string): number {
  return parseIssueRangeDetailed(input).total;
}
  if (!input || !input.trim()) {
    throw new Error('Issue range cannot be empty');
  }

  const trimmedInput = input.trim();
  const result: string[] = [];
  const parts = trimmedInput.split(',');

  for (const part of parts) {
    const trimmedPart = part.trim();
    if (!trimmedPart) {
      continue;
    }

    if (trimmedPart.includes('-')) {
      // Try to parse as an integer range
      const dashIdx = trimmedPart.indexOf('-');
      const left = trimmedPart.slice(0, dashIdx).trim();
      const right = trimmedPart.slice(dashIdx + 1).trim();

      const start = Number.parseInt(left, 10);
      const end = Number.parseInt(right, 10);

      // Verify entire string is numeric (matches backend int() behavior which rejects partial parses like "5a")
      // Use regex to allow zero-padded numbers while rejecting trailing non-numeric characters
      const isNumeric = (str: string) => /^\d+$/.test(str);
      if (!Number.isNaN(start) && !Number.isNaN(end) && isNumeric(left) && isNumeric(right)) {
        if (start < 0 || end < 0) {
          throw new Error('Range endpoints must be >= 0');
        }
        if (start > end) {
          throw new Error(`Range start (${start}) cannot exceed end (${end})`);
        }
        // Check range size BEFORE expansion to prevent DoS (matches backend check)
        const rangeSize = end - start + 1;
        if (rangeSize > MAX_ISSUES) {
          throw new Error(`Range too large: ${rangeSize} issues (max ${MAX_ISSUES})`);
        }
        // Check cumulative total to prevent combining multiple large ranges
        if (result.length + rangeSize > MAX_ISSUES) {
          throw new Error(`Total issues would exceed maximum of ${MAX_ISSUES}`);
        }
        for (let i = start; i <= end; i++) {
          result.push(String(i));
        }
      } else {
        // Not a valid integer range — store as literal
        if (trimmedPart.length > MAX_LITERAL_LENGTH) {
          throw new Error(`Issue identifier too long (max ${MAX_LITERAL_LENGTH} chars)`);
        }
        result.push(trimmedPart);
      }
    } else {
      // Single token — accept any non-empty string
      if (trimmedPart.length > MAX_LITERAL_LENGTH) {
        throw new Error(`Issue identifier too long (max ${MAX_LITERAL_LENGTH} chars)`);
      }
      result.push(trimmedPart);
    }
  }

  // Deduplicate while preserving order
  const seen = new Set<string>();
  const uniqueResult: string[] = [];

  for (const issue of result) {
    if (!seen.has(issue)) {
      seen.add(issue);
      uniqueResult.push(issue);
    }
  }

  if (uniqueResult.length > MAX_ISSUES) {
    throw new Error(`Cannot create more than ${MAX_ISSUES} issues at once`);
  }

  return uniqueResult.length;
}
