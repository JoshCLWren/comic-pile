import { vi, type Mock } from 'vitest'
import type { HttpClient } from '../services/httpClient'

/**
 * In-test HTTP transport double.
 *
 * Every method is a `vi.fn()` spy shaped to satisfy {@link HttpClient}, so
 * service factories under test receive a real interface value instead of a
 * replaced module. Methods resolve to `undefined` unless a test configures
 * them, so assertions depend only on behaviour the test sets up explicitly.
 */
export type HttpClientStub = { [K in keyof HttpClient]: Mock }

/**
 * Build a fresh {@link HttpClientStub}.
 *
 * @returns A transport double whose methods resolve to `undefined` by default.
 */
export function createHttpClientStub(): HttpClientStub {
  return {
    get: vi.fn(async () => undefined),
    delete: vi.fn(async () => undefined),
    post: vi.fn(async () => undefined),
    put: vi.fn(async () => undefined),
    patch: vi.fn(async () => undefined),
  }
}
