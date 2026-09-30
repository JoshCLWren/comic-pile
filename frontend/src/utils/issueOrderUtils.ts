import { parseIssueRangeTokens } from './issueParser';

/**
 * Where a newly added run of issues belongs in a thread's canonical issue order.
 *
 * - `start`: no existing ordinary issue sorts before the addition, so the new
 *   issues go to position 1.
 * - `after`: the new issues go immediately after the reported issue.
 * - `end`: ordering is ambiguous for this addition, so the existing canonical
 *   order is preserved and the new issues are appended.
 */
export type NaturalInsertAnchor =
  | { kind: 'start' }
  | { kind: 'after'; issueId: number }
  | { kind: 'end' };

/** Minimal issue shape needed to decide natural ordering. */
export interface OrderedIssue {
  id: number;
  issue_number: string;
}

/**
 * Report whether an issue identifier is an ordinary positive number.
 *
 * Irregular provider numbering is deliberately excluded so natural ordering is
 * never faked for it: `0` (the ubiquitous free prequel), decimals/fractions such
 * as `1.5` or `½`, negative values, and named specials such as `Annual 1`.
 */
export function isOrdinaryNumericIssueNumber(issueNumber: string): boolean {
  return /^[1-9]\d*$/.test(issueNumber);
}

/**
 * Decide where a requested issue range belongs in an existing thread order.
 *
 * The decision is deterministic and independent of the order the values were
 * typed: it only depends on the set of identifiers that are actually new. When
 * the addition mixes ordinary and irregular identifiers, or contains no ordinary
 * identifier at all, ordering is ambiguous and the existing order is preserved.
 *
 * @param existingIssues - Current thread issues in canonical order.
 * @param issueRange - Range string such as "2", "19-24" or "1, 3, 5-7".
 * @returns The anchor the new issues should be inserted relative to.
 * @throws Error if the range string is invalid.
 */
export function resolveNaturalInsertAnchor(
  existingIssues: readonly OrderedIssue[],
  issueRange: string,
): NaturalInsertAnchor {
  const requestedNumbers = parseIssueRangeTokens(issueRange);
  const existingNumbers = new Set(existingIssues.map((issue) => issue.issue_number));
  const addedNumbers = requestedNumbers.filter(
    (issueNumber) => !existingNumbers.has(issueNumber),
  );

  // Nothing to order against: the create contract already lands these first.
  if (existingIssues.length === 0 || addedNumbers.length === 0) {
    return { kind: 'end' };
  }

  const addedOrdinaryNumbers = addedNumbers.filter(isOrdinaryNumericIssueNumber);

  // Any irregular identifier in the run makes the whole placement ambiguous.
  if (addedOrdinaryNumbers.length !== addedNumbers.length) {
    return { kind: 'end' };
  }

  let smallestAdded = Number.POSITIVE_INFINITY;
  for (const issueNumber of addedOrdinaryNumbers) {
    smallestAdded = Math.min(smallestAdded, Number(issueNumber));
  }

  // Anchor after the last existing ordinary issue that sorts before the
  // addition. Walking the canonical order (rather than sorting by number) keeps
  // any intentionally non-numeric prefix of the thread where the reader put it.
  let anchorIssueId: number | null = null;
  for (const issue of existingIssues) {
    if (!isOrdinaryNumericIssueNumber(issue.issue_number)) {
      continue;
    }
    if (Number(issue.issue_number) < smallestAdded) {
      anchorIssueId = issue.id;
    }
  }

  return anchorIssueId === null ? { kind: 'start' } : { kind: 'after', issueId: anchorIssueId };
}

/**
 * Build the full thread issue-id order that persists a natural insertion, or
 * `null` when the create call alone already persisted it.
 *
 * Create persists the run in the order the values were typed, so a run typed
 * out of order (e.g. "5, 4") would land out of natural order. The natural
 * anchors guarantee the run is ordinary numeric, so the block is normalized to
 * ascending numbers on the canonical `Issue.position` path instead of
 * inventing a second ordering source of truth. Existing issues keep whatever
 * canonical order the reader established.
 *
 * No reorder is needed when an `after` creation already landed the run in
 * natural order, and never for an ambiguous `end` append.
 *
 * @param existingIssues - Current thread issues in canonical order.
 * @param anchor - The natural insert anchor for this addition.
 * @param createdIssues - Issues the create call returned, in creation order.
 * @returns The full ordered id list to send to the reorder endpoint, or null.
 */
export function naturalInsertFullOrder(
  existingIssues: readonly OrderedIssue[],
  anchor: NaturalInsertAnchor,
  createdIssues: readonly OrderedIssue[],
): number[] | null {
  if (anchor.kind === 'end' || createdIssues.length === 0) {
    return null;
  }

  const createdSorted = [...createdIssues].sort(
    (a, b) => Number(a.issue_number) - Number(b.issue_number),
  );
  const blockIsNatural = createdSorted.every(
    (issue, index) => issue.id === createdIssues[index].id,
  );

  if (anchor.kind === 'after' && blockIsNatural) {
    return null;
  }

  if (anchor.kind === 'start') {
    return [
      ...createdSorted.map((issue) => issue.id),
      ...existingIssues.map((issue) => issue.id),
    ];
  }

  const anchorIndex = existingIssues.findIndex((issue) => issue.id === anchor.issueId);
  return [
    ...existingIssues.slice(0, anchorIndex + 1).map((issue) => issue.id),
    ...createdSorted.map((issue) => issue.id),
    ...existingIssues.slice(anchorIndex + 1).map((issue) => issue.id),
  ];
}
