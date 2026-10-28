import { describe, expect, it } from 'vitest'
import { readingModeLabel, formatSessionMode } from '../types/rollBootstrap'

describe('readingModeLabel', () => {
  it.each([
    ['deep', 'Deep'],
    ['familiar', 'Familiar'],
    ['balanced', 'Balanced'],
    ['light', 'Light'],
    ['momentum', 'Momentum'],
    ['explore', 'Explore'],
    ['random', 'Random'],
  ])('capitalizes %s to %s', (input: string, expected: string) => {
    expect(readingModeLabel(input)).toBe(expected)
  })

  it.each([
    ['Deep', 'Deep'],
    ['DEEP', 'Deep'],
    ['  deep  ', 'Deep'],
    ['DeEp', 'Deep'],
  ])('normalizes %s to %s', (input: string, expected: string) => {
    expect(readingModeLabel(input)).toBe(expected)
  })

  it.each([
    ['unknown', 'unknown'],
    ['CustomValue', 'CustomValue'],
  ])('returns unknown input unchanged: %s', (input: string, expected: string) => {
    expect(readingModeLabel(input)).toBe(expected)
  })

  it.each([
    [null, ''],
    [undefined, ''],
    ['', ''],
  ])('returns empty string for %s', (input: string | null | undefined, expected: string) => {
    expect(readingModeLabel(input)).toBe(expected)
  })
})

describe('formatSessionMode', () => {
  it.each([
    [{ bandwidth: 'deep', intent: 'familiar' }, 'Deep · Familiar'],
    [{ bandwidth: 'balanced', intent: 'balanced' }, 'Balanced · Balanced'],
    [{ bandwidth: 'light', intent: 'balanced' }, 'Light · Balanced'],
    [{ bandwidth: 'balanced', intent: 'random' }, 'Balanced · Random'],
  ])('joins bandwidth and intent: %s', (input: { bandwidth: string; intent: string }, expected: string) => {
    expect(formatSessionMode(input)).toBe(expected)
  })

  it.each([
    [{ bandwidth: 'deep', intent: null }, 'Deep'],
    [{ bandwidth: null, intent: 'familiar' }, 'Familiar'],
  ])('omits missing part: %s', (input: { bandwidth: string | null; intent: string | null }, expected: string) => {
    expect(formatSessionMode(input)).toBe(expected)
  })

  it.each([
    [null, ''],
    [undefined, ''],
  ])('returns empty string for %s', (mode: { bandwidth: string; intent: string } | null | undefined, expected: string) => {
    expect(formatSessionMode(mode)).toBe(expected)
  })

  it.each([
    [{ bandwidth: '', intent: 'familiar' }, 'Familiar'],
    [{ bandwidth: 'deep', intent: '' }, 'Deep'],
    [{ bandwidth: '', intent: '' }, ''],
  ])('treats empty string as missing: %s', (input: { bandwidth: string; intent: string }, expected: string) => {
    expect(formatSessionMode(input)).toBe(expected)
  })
})
