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
 * Characters that carry no visible identity: zero-width spaces, joiners, bidi
 * controls, and similar formatting characters. An identifier built only from
 * these renders as an empty issue number ("#"), which is how a phantom chip
 * with no identity gets created.
 */
const INVISIBLE_CHARACTER_PATTERN =
  /[\u00AD\u180E\u200B-\u200F\u202A-\u202E\u2060-\u2064\uFEFF]/;

const INVISIBLE_CHARACTER_PATTERN_GLOBAL = new RegExp(
  INVISIBLE_CHARACTER_PATTERN.source,
  'g',
);

/**
 * Whether the value contains a character that renders as nothing.
 */
function hasInvisibleCharacters(value: string): boolean {
  return INVISIBLE_CHARACTER_PATTERN.test(value);
}

/**
 * The visible content of a value, with invisible characters removed.
 */
function visibleContent(value: string): string {
  return value.replace(INVISIBLE_CHARACTER_PATTERN_GLOBAL, '').trim();
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
 * Issue expansion, dedupe, limits, and thrown messages must stay in sync with
 * app/utils/issue_parser.py. The recognized-literal heuristic behind `warnings`
 * and `breakdown` is a preview-only affordance (#3262): it never changes what is
 * submitted, and the backend still accepts any literal identifier.
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

/**
 * Why a token cannot be staged as an issue.
 */
export type IssueRangeInvalidReason =
  /** The token carries no issue number at all, e.g. "abc". */
  | 'no-issue-number'
  /** The token is a negative number, e.g. "-3". */
  | 'negative'
  /** The token is a half-written range, e.g. "19-" or "1-". */
  | 'malformed-range'
  /** The token is built from characters that render as nothing. */
  | 'invisible-characters';

/**
 * Result of validating an issue-range input before it is staged.
 */
export interface IssueRangeValidationResult {
  /** True when the input is empty (nothing to validate) or fully valid. */
  valid: boolean;
  /** True when the input carries no user content at all. */
  empty: boolean;
  /** The trimmed input. */
  normalized: string;
  /** Parsed issue identifiers. Empty when the input is invalid. */
  issues: string[];
  /** The tokens that failed validation. */
  invalidTokens: string[];
  /** Why the tokens failed validation. */
  invalidReason: IssueRangeInvalidReason | null;
  /** A user-facing error message. Null when the input is valid or empty. */
  error: string | null;
}

/**
 * Guidance appended to every staging error so the reader knows what a valid
 * issue entry looks like.
 */
const ISSUE_RANGE_INPUT_HINT =
  'Enter an issue number or range (19-24), or a named issue such as Annual 1.';

/**
 * Quote the offending tokens for an error message.
 */
function describeTokens(tokens: string[]): string {
  const quoted = tokens.map((token) => `'${token}'`);
  const last = quoted[quoted.length - 1];
  if (quoted.length === 1) {
    return quoted[0];
  }
  return `${quoted.slice(0, -1).join(', ')} and ${last}`;
}

/**
 * Build the user-facing message for a rejected input.
 */
function buildInvalidMessage(tokens: string[], reason: IssueRangeInvalidReason): string {
  if (reason === 'invisible-characters') {
    return `Invalid issue: that entry contains invisible characters. ${ISSUE_RANGE_INPUT_HINT}`;
  }

  const subject = describeTokens(tokens);
  const label = tokens.length === 1 ? 'Invalid issue' : 'Invalid issues';
  const verb = tokens.length === 1 ? 'is' : 'are';

  let reasonClause = '';
  if (reason === 'negative') {
    reasonClause = ' Issue numbers cannot be negative.';
  } else if (reason === 'malformed-range') {
    reasonClause = ' A range needs a number on both sides, like 19-24.';
  }

  return `${label}: ${subject} ${verb} not a valid issue number.${reasonClause} ${ISSUE_RANGE_INPUT_HINT}`;
}

/**
 * Validate an issue-range input before it is staged as a pending issue chip.
 *
 * The backend parser deliberately accepts any literal identifier, so the
 * client needs its own guard: without one, arbitrary text such as "abc", a
 * negative number such as "-3", or a zero-width character becomes a phantom
 * issue chip that is one Save away from becoming a real record (issue #3586).
 *
 * This guard is deliberately stricter than the backend parser and has no
 * backend counterpart. It accepts:
 *
 * - issue numbers ("19", "0");
 * - numeric ranges ("19-24");
 * - recognized named forms ("Annual 1", "Special 2", "½", "FCBD 2024",
 *   "#19", "Vol. 2 #5");
 * - other numbered labels that carry an issue number ("2b", "1.5",
 *   "1-Annual").
 *
 * It rejects anything else, because a token without an issue number is not
 * an issue. The tokenization itself still comes from
 * {@link parseIssueRangeDetailed} so the guard stays aligned with the
 * backend's parser.
 *
 * @param input - Raw text from the issue entry field
 * @returns The validation result, including a user-facing error message
 */
export function validateIssueRangeForStaging(input: string): IssueRangeValidationResult {
  const normalized = input.trim();

  if (!normalized) {
    return {
      valid: true,
      empty: true,
      normalized,
      issues: [],
      invalidTokens: [],
      invalidReason: null,
      error: null,
    };
  }

  if (hasInvisibleCharacters(normalized)) {
    return {
      valid: false,
      empty: false,
      normalized,
      issues: [],
      invalidTokens: [],
      invalidReason: 'invisible-characters',
      error: buildInvalidMessage([], 'invisible-characters'),
    };
  }

  let detail: ParsedIssueRangeDetail;
  try {
    detail = parseIssueRangeDetailed(normalized);
  } catch (error: unknown) {
    return {
      valid: false,
      empty: false,
      normalized,
      issues: [],
      invalidTokens: [],
      invalidReason: null,
      error: error instanceof Error ? error.message : 'Invalid issue range',
    };
  }

  const invalidTokens: string[] = [];
  let invalidReason: IssueRangeInvalidReason | null = null;

  for (const item of detail.breakdown) {
    if (item.type !== 'unrecognized-literal') {
      continue;
    }

    let reason: IssueRangeInvalidReason;
    if (item.token.startsWith('-')) {
      reason = /^-\d/.test(item.token) ? 'negative' : 'malformed-range';
    } else if (item.token.endsWith('-')) {
      reason = 'malformed-range';
    } else if (!/\d/.test(item.token)) {
      reason = 'no-issue-number';
    } else {
      // A numbered label such as "2b" or "1-Annual" still identifies an issue.
      continue;
    }

    invalidTokens.push(item.token);
    invalidReason = invalidReason ?? reason;
  }

  if (invalidTokens.length > 0) {
    const reason = invalidReason ?? 'no-issue-number';
    return {
      valid: false,
      empty: false,
      normalized,
      issues: [],
      invalidTokens,
      invalidReason: reason,
      error: buildInvalidMessage(invalidTokens, reason),
    };
  }

  return {
    valid: true,
    empty: false,
    normalized,
    issues: detail.issues,
    invalidTokens: [],
    invalidReason: null,
    error: null,
  };
}

/**
 * Whether the input carries any content worth validating.
 *
 * Whitespace-only input is empty, but input built from invisible characters
 * is not: it renders as nothing and would create an unnamed issue.
 */
export function hasIssueRangeContent(input: string): boolean {
  return input.trim().length > 0 || visibleContent(input).length > 0;
}
