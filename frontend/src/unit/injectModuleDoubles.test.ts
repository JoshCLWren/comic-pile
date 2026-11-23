import { expect, it, vi } from 'vitest'
import { isFunction } from '../utils/runtimeChecks'
import { injectModuleDoubles } from './injectModuleDoubles'

await injectModuleDoubles(await import('../utils/runtimeChecks'), async (importOriginal) => {
  const actual = await importOriginal<typeof import('../utils/runtimeChecks')>()
  return {
    isFunction: (value: unknown) => actual.isFunction(value),
  }
})

it('keeps original exports stable when a replacement wraps them', () => {
  const callback = () => undefined

  expect(isFunction(callback)).toBe(true)
  expect(vi.mocked(isFunction)).toHaveBeenCalledTimes(1)
})
