import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useRollPageState } from '../pages/RollPage/useRollPageState'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
})

it('returns the document to the top when the rating view closes', () => {
  const scrollTo = vi.mocked(window.scrollTo)
  const { result } = renderHook(() => useRollPageState())

  expect(scrollTo).not.toHaveBeenCalled()

  act(() => {
    result.current.setIsRatingView(true)
  })
  expect(scrollTo).not.toHaveBeenCalled()

  act(() => {
    result.current.setIsRatingView(false)
  })

  expect(scrollTo).toHaveBeenCalledTimes(1)
  expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'auto' })
})
