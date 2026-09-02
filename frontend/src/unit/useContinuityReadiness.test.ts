import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useContinuityReadiness } from '../hooks/useContinuityReadiness'

describe('useContinuityReadiness', () => {
  it('does not perform a second readiness evaluation after Roll selection', () => {
    const { result } = renderHook(() => useContinuityReadiness(7))
    expect(result.current).toMatchObject({ readiness: null, isLoading: false, error: null })
  })
})
