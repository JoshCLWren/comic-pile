import type { DieStateResponse } from '../../generated/nativeV2Client'
import type { RollBootstrapResponse } from '../../types/rollBootstrap'

/**
 * Selected die for #4352, derived during render (no effect/no state):
 * scoped die-state wins, then bootstrap manual pin, then bootstrap
 * event-derived die, defaulting to d6. A failed scoped query reaches here
 * as `undefined` (see `isScopedDieStateError` in `RollPage`), so the
 * bootstrap fallback covers the error path.
 */
export function resolveRollSelectedDie(
  scopedDieState: DieStateResponse | null | undefined,
  bootstrap: Pick<RollBootstrapResponse, 'manual_die' | 'current_die'> | null | undefined,
): number {
  return scopedDieState?.die ?? bootstrap?.manual_die ?? bootstrap?.current_die ?? 6
}
