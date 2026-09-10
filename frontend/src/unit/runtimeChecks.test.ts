import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  isBoolean,
  isBrowser,
  isFunction,
  isNonNullObject,
  isNonEmptyString,
  isNumber,
  isObject,
  isPlainObject,
  isString,
  isWindowDefined,
  hasProperty,
} from '../utils/runtimeChecks'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('runtimeChecks', () => {
  describe('isBrowser', () => {
    it('returns false when document is absent', () => {
      vi.stubGlobal('document', undefined)
      vi.stubGlobal('localStorage', undefined)
      expect(isBrowser()).toBe(false)
    })

    it('returns false when document exists but localStorage is absent', () => {
      vi.stubGlobal('document', {})
      vi.stubGlobal('localStorage', undefined)
      expect(isBrowser()).toBe(false)
    })

    it('returns true when both document and localStorage exist', () => {
      vi.stubGlobal('document', {})
      vi.stubGlobal('localStorage', {})
      expect(isBrowser()).toBe(true)
    })
  })

  describe('isWindowDefined', () => {
    it('returns false when window is absent', () => {
      vi.stubGlobal('window', undefined)
      expect(isWindowDefined()).toBe(false)
    })

    it('returns true when window exists', () => {
      vi.stubGlobal('window', {})
      expect(isWindowDefined()).toBe(true)
    })
  })

  describe('isFunction', () => {
    it('matches regular functions', () => {
      expect(isFunction(() => {})).toBe(true)
    })

    it('matches async functions', () => {
      expect(isFunction(async () => {})).toBe(true)
    })

    it('matches generator functions', () => {
      expect(isFunction(function* () {})).toBe(true)
    })

    it('rejects non-functions', () => {
      expect(isFunction(null)).toBe(false)
      expect(isFunction(undefined)).toBe(false)
      expect(isFunction(42)).toBe(false)
      expect(isFunction('str')).toBe(false)
      expect(isFunction({})).toBe(false)
    })
  })

  describe('isString', () => {
    it('matches strings', () => {
      expect(isString('')).toBe(true)
      expect(isString('hello')).toBe(true)
    })

    it('rejects non-strings', () => {
      expect(isString(null)).toBe(false)
      expect(isString(undefined)).toBe(false)
      expect(isString(42)).toBe(false)
      expect(isString({})).toBe(false)
      expect(isString([])).toBe(false)
    })
  })

  describe('isNumber', () => {
    it('matches finite numbers', () => {
      expect(isNumber(0)).toBe(true)
      expect(isNumber(42)).toBe(true)
      expect(isNumber(-1)).toBe(true)
    })

    it('rejects NaN and infinities', () => {
      expect(isNumber(NaN)).toBe(false)
      expect(isNumber(Infinity)).toBe(false)
      expect(isNumber(-Infinity)).toBe(false)
    })

    it('rejects non-numbers', () => {
      expect(isNumber(null)).toBe(false)
      expect(isNumber(undefined)).toBe(false)
      expect(isNumber('42')).toBe(false)
      expect(isNumber({})).toBe(false)
    })
  })

  describe('isBoolean', () => {
    it('matches booleans', () => {
      expect(isBoolean(true)).toBe(true)
      expect(isBoolean(false)).toBe(true)
    })

    it('rejects non-booleans', () => {
      expect(isBoolean(null)).toBe(false)
      expect(isBoolean(0)).toBe(false)
      expect(isBoolean('true')).toBe(false)
      expect(isBoolean({})).toBe(false)
    })
  })

  describe('isObject', () => {
    it('matches plain objects', () => {
      expect(isObject({})).toBe(true)
      expect(isObject({ a: 1 })).toBe(true)
    })

    it('rejects null, undefined, and non-objects', () => {
      expect(isObject(null)).toBe(false)
      expect(isObject(undefined)).toBe(false)
      expect(isObject(42)).toBe(false)
      expect(isObject('str')).toBe(false)
      expect(isObject([])).toBe(false)
    })
  })

  describe('isNonNullObject', () => {
    it('matches plain objects and errors', () => {
      expect(isNonNullObject({})).toBe(true)
      expect(isNonNullObject(new Error('boom'))).toBe(true)
    })

    it('rejects null, undefined, and non-objects', () => {
      expect(isNonNullObject(null)).toBe(false)
      expect(isNonNullObject(undefined)).toBe(false)
      expect(isNonNullObject(42)).toBe(false)
      expect(isNonNullObject('str')).toBe(false)
    })
  })

  describe('isPlainObject', () => {
    it('delegates to isObject', () => {
      expect(isPlainObject({})).toBe(true)
      expect(isPlainObject(null)).toBe(false)
      expect(isPlainObject([])).toBe(false)
    })
  })

  describe('hasProperty', () => {
    it('returns true when the key exists', () => {
      expect(hasProperty({ a: 1 }, 'a')).toBe(true)
    })

    it('returns false when the key is absent', () => {
      expect(hasProperty({ a: 1 }, 'b')).toBe(false)
    })
  })

  describe('isNonEmptyString', () => {
    it('matches non-empty strings', () => {
      expect(isNonEmptyString('a')).toBe(true)
    })

    it('rejects empty strings and non-strings', () => {
      expect(isNonEmptyString('')).toBe(false)
      expect(isNonEmptyString(null)).toBe(false)
      expect(isNonEmptyString(undefined)).toBe(false)
      expect(isNonEmptyString(42)).toBe(false)
    })
  })
})
