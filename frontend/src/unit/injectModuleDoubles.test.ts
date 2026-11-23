import { expect, it, vi } from 'vitest'
import { injectModuleDoubles } from './injectModuleDoubles'

const moduleExports = {
  double: (value: number) => value * 2,
}

await injectModuleDoubles(moduleExports, async (importOriginal) => {
  const actual = await importOriginal<typeof moduleExports>()
  return {
    double: (value: number) => actual.double(value),
  }
})

it('keeps original exports stable when a replacement wraps them', () => {
  expect(moduleExports.double(2)).toBe(4)
  expect(vi.mocked(moduleExports.double)).toHaveBeenCalledWith(2)
})
