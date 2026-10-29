import { useQuery } from '@tanstack/react-query';
import { threadsApi } from '../services/api-threads';
import type { CheckPotentialDuplicatesRequest, PotentialDuplicateMatch } from '../types';
import { queryKeys } from '../query/queryKeys';
import { useDebounce } from './useDebounce';

/**
 * How long the reader must stop typing before the library is checked.
 *
 * The advisory is a supporting signal, not a field validator, so a short pause
 * keeps a rename from firing one request per keystroke while still feeling
 * immediate.
 */
export const POTENTIAL_DUPLICATE_DEBOUNCE_MS = 350;

interface PotentialDuplicatesParams {
  /** Candidate title as typed by the reader. */
  title: string;
  /** Candidate format, used as disambiguating context by the server. */
  format: string;
  /** Canonical ComicVine volume when the candidate already has one. */
  comicvineVolumeId?: number;
  /** Series being renamed, so a rename never warns about itself. */
  excludeThreadId?: number;
  /** False while the owning dialog is closed, so no request is made. */
  enabled?: boolean;
}

export interface PotentialDuplicatesResult {
  /** Possible existing volumes, strongest first. Empty until a check returns. */
  matches: PotentialDuplicateMatch[];
  /** True while the candidate is being checked (including the debounce). */
  isChecking: boolean;
  /** True when the advisory lookup failed; the forms stay usable. */
  isError: boolean;
}

/**
 * Ask the advisory duplicate endpoint about a candidate series (#3612).
 *
 * The lookup is read-only and nonblocking: it never creates, renames, merges,
 * or deletes anything. A failed or pending check simply renders no warning, so
 * an advisory outage can never stop the reader from adding or renaming a
 * series.
 *
 * Args:
 *   params: Candidate title/format plus optional volume identity, the thread
 *     being renamed, and whether the owning dialog is open.
 *
 * Returns:
 *   Matches to display, whether a check is in flight, and whether it failed.
 */
export function usePotentialDuplicates({
  title,
  format,
  comicvineVolumeId,
  excludeThreadId,
  enabled = true,
}: PotentialDuplicatesParams): PotentialDuplicatesResult {
  const trimmedTitle = title.trim();
  const trimmedFormat = format.trim();
  const debouncedTitle = useDebounce(trimmedTitle, POTENTIAL_DUPLICATE_DEBOUNCE_MS);
  const canCheck =
    enabled &&
    trimmedTitle.length > 0 &&
    debouncedTitle.length > 0 &&
    trimmedFormat.length > 0;

  const request: CheckPotentialDuplicatesRequest = {
    title: debouncedTitle,
    format: trimmedFormat,
  };
  if (comicvineVolumeId !== undefined) {
    request.comicvine_volume_id = comicvineVolumeId;
  }
  if (excludeThreadId !== undefined) {
    request.exclude_thread_id = excludeThreadId;
  }

  const query = useQuery({
    queryKey: queryKeys.thread.potentialDuplicates({
      title: debouncedTitle,
      format: trimmedFormat,
      comicvine_volume_id: comicvineVolumeId,
      exclude_thread_id: excludeThreadId,
    }),
    queryFn: () => threadsApi.checkPotentialDuplicates(request),
    enabled: canCheck,
  });

  return {
    matches: canCheck ? query.data?.matches ?? [] : [],
    isChecking: canCheck && (query.isPending || debouncedTitle !== trimmedTitle),
    isError: canCheck && query.isError,
  };
}
