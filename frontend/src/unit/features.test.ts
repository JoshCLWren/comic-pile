import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadFeatures(envValue: string | undefined) {
  if (envValue === undefined) {
    vi.unstubAllEnvs()
  } else {
    vi.stubEnv('VITE_FEATURE_READING_MODE_QUIZ', envValue)
  }
  vi.resetModules()
  return import('../config/features')
}

describe('frontend feature flags (issue #1945)', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('defaults the reading-mode quiz flag to disabled when the env var is unset', async () => {
    const { FEATURES } = await loadFeatures(undefined)
    expect(FEATURES.readingModeQuiz).toBe(false)
  })

  it('defaults to disabled when the env var is an empty string', async () => {
    const { FEATURES } = await loadFeatures('')
    expect(FEATURES.readingModeQuiz).toBe(false)
  })

  it('enables the flag when the env var is set to true', async () => {
    const { FEATURES } = await loadFeatures('true')
    expect(FEATURES.readingModeQuiz).toBe(true)
  })

  it('enables the flag when the env var is set to 1', async () => {
    const { FEATURES } = await loadFeatures('1')
    expect(FEATURES.readingModeQuiz).toBe(true)
  })

  it('treats any other value as disabled', async () => {
    const { FEATURES } = await loadFeatures('yes')
    expect(FEATURES.readingModeQuiz).toBe(false)
  })

  it('exposes the resolved flags on the window for build-time probes', async () => {
    const { FEATURES } = await loadFeatures('true')
    expect(window.__COMIC_PILE_FEATURES__).toEqual(FEATURES)
    expect(window.__COMIC_PILE_FEATURES__?.readingModeQuiz).toBe(true)
  })
})