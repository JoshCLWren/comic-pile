import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useContinuityReadiness } from '../hooks/useContinuityReadiness'

describe('useContinuityReadiness compatibility shim', () => {
  it('stays inert even when an issue id is present', () => {
    const { result } = renderHook(() => useContinuityReadiness(7, { skip: false }))
    expect(result.current.readiness).toBeNull()
    expect(result.current.isLoading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(() => result.current.refetch()).not.toThrow()
  })
})
