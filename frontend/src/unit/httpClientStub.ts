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
export type HttpClientStub = HttpClient & { [K in keyof HttpClient]: Mock }

/**
 * Build a fresh {@link HttpClientStub}.
 *
 * @returns A transport double whose methods resolve to `undefined` by default.
 */
export function createHttpClientStub(): HttpClientStub {
  // SAFETY: mocks are typed as generic Mock; tests configure return values explicitly.
  // SAFETY: vi.fn returns Mock; explicit widening avoids inference mismatch with HttpClient generics.
  const request = vi.fn(async () => undefined) as Mock
  // SAFETY: vi.fn returns Mock; explicit widening avoids inference mismatch with HttpClient generics.
  const get = vi.fn(async () => undefined) as Mock
  // SAFETY: vi.fn returns Mock; explicit widening avoids inference mismatch with HttpClient generics.
  const del = vi.fn(async () => undefined) as Mock
  // SAFETY: vi.fn returns Mock; explicit widening avoids inference mismatch with HttpClient generics.
  const head = vi.fn(async () => undefined) as Mock
  // SAFETY: vi.fn returns Mock; explicit widening avoids inference mismatch with HttpClient generics.
  const post = vi.fn(async () => undefined) as Mock
  // SAFETY: vi.fn returns Mock; explicit widening avoids inference mismatch with HttpClient generics.
  const put = vi.fn(async () => undefined) as Mock
  // SAFETY: vi.fn returns Mock; explicit widening avoids inference mismatch with HttpClient generics.
  const patch = vi.fn(async () => undefined) as Mock

  // SAFETY: object literal satisfies HttpClient methods; Mapped type ensures all keys are Mock.
  // Avoid chained type assertions by constructing the object with the correct type upfront.
  const stub = {
    request,
    get,
    delete: del,
    head,
    post,
    put,
    patch,
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    getUri: vi.fn(() => ''),
    options: vi.fn(async () => undefined),
    postForm: vi.fn(async () => undefined),
    putForm: vi.fn(async () => undefined),
    patchForm: vi.fn(async () => undefined),
    query: vi.fn(async () => undefined),
    create: vi.fn(),
  }
  // SAFETY: constructed object satisfies HttpClientStub.
  return stub as HttpClientStub
}
