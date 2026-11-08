import type { DieStateResponse } from '../../generated/nativeV2Client'

/**
 * Selected die for #4352, derived during render (no effect/no state):
 * scoped die-state only, defaulting to d6. A failed scoped query reaches
 * here as `undefined` (see `isScopedDieStateError` in `RollPage`), so the
 * d6 default covers the pending and error paths while bootstrap no longer
 * carries die fields.
 */
export function resolveRollSelectedDie(
  scopedDieState: DieStateResponse | null | undefined,
): number {
  return scopedDieState?.die ?? 6
}
