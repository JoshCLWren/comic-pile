import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readValue, service, untouched } from './injectModuleDoubles.fixture'
import { injectModuleDoubles } from './injectModuleDoubles'

let originalReadResult = ''
let originalServiceReadResult = ''

const readDouble = vi.fn<(value: string) => string>((value) => `double:${value}`)
const serviceDouble = {
  read: vi.fn<(value: number) => string>((value) => `double:${value}`),
}

await injectModuleDoubles(await import('./injectModuleDoubles.fixture'), async (importOriginal) => {
  const actual = await importOriginal<typeof import('./injectModuleDoubles.fixture')>()
  originalReadResult = actual.readValue('original')
  originalServiceReadResult = actual.service.read(7)
  return { readValue: readDouble, service: serviceDouble }
})

beforeEach(() => {
  vi.resetAllMocks()
  readDouble.mockImplementation((value) => `double:${value}`)
  serviceDouble.read.mockImplementation((value) => `double:${value}`)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('injectModuleDoubles', () => {
  it('preserves the real module for partial implementations and untouched exports', () => {
    expect(originalReadResult).toBe('real:original')
    expect(originalServiceReadResult).toBe('real:7')
    expect(untouched).toBe('untouched')
    expect(readValue('value')).toBe('double:value')
    expect(service.read(3)).toBe('double:3')
    expect(readDouble).toHaveBeenCalledExactlyOnceWith('value')
    expect(serviceDouble.read).toHaveBeenCalledExactlyOnceWith(3)
  })

  it('reinstalls suite doubles after a test restores all spies', () => {
    expect(vi.isMockFunction(readValue)).toBe(true)
    expect(readValue('again')).toBe('double:again')
    expect(service.read(4)).toBe('double:4')
    expect(readDouble).toHaveBeenCalledExactlyOnceWith('again')
    expect(serviceDouble.read).toHaveBeenCalledExactlyOnceWith(4)
  })
})
