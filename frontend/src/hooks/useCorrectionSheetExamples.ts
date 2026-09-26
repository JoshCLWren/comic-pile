import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { sessionApi } from '../services/api-sessions';
import { queryKeys } from '../query/queryKeys';
import type { CorrectionChoiceId } from '../types';

/**
 * Per-choice example lines for the Roll correction sheet.
 *
 * The backend returns an explicit field per choice, so the map is normalized
 * here: a missing or null entry is a deliberate "no honest example" and must not
 * fall back to another choice's example.
 */
export type CorrectionExamples = Record<CorrectionChoiceId, string | null>;

/**
 * Personalized example lines for the correction sheet choices.
 *
 * One bounded request serves the whole sheet, and it is only issued while the
 * sheet is actually open so a reader who never corrects a roll never pays for
 * the lookup. Missing history is not an error: the sheet renders plain copy
 * without an example line.
 */
export function useCorrectionSheetExamples(enabled: boolean) {
  const query = useQuery({
    queryKey: queryKeys.session.correctionExamples(),
    queryFn: () => sessionApi.getCorrectionExamples(),
    enabled,
    // Examples are derived from rating history that only changes when the
    // reader rates something, so a short window keeps them from going stale
    // between corrections without refetching on every sheet open.
    staleTime: 5 * 60 * 1000,
  });

  return useMemo(() => {
    const data = query.data;
    const examples: CorrectionExamples | undefined = data
      ? {
          even_easier: data.even_easier ?? null,
          keep_level_different: data.keep_level_different ?? null,
          something_familiar: data.something_familiar ?? null,
          something_different: data.something_different ?? null,
          pure_random: data.pure_random ?? null,
        }
      : undefined;

    return {
      examples,
      isPending: query.isPending,
      isError: query.isError,
      error: query.error,
    };
  }, [query]);
}
