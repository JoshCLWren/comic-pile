import { vi, type Mock } from 'vitest'
import type { HttpClient } from '../services/httpClient'

/**
 * Faithful in-test stand-in for the transport `createApiClient` configures.
 *
 * It records every request and captures the interceptors the client registers,
 * so tests exercise the real client wiring and interceptor pipeline instead of
 * replacing a module.
 */
export type TransportDouble = {
  [K in keyof HttpClient]: Mock
} & {
  request: Mock
  interceptors: {
    request: { use: Mock; eject: Mock; clear: Mock }
    response: { use: Mock; eject: Mock; clear: Mock }
  }
}

/**
 * Build a fresh {@link TransportDouble}.
 *
 * @returns A transport double whose request methods resolve to `undefined`.
 */
export function createTransportDouble(): TransportDouble {
  return {
    request: vi.fn(async () => undefined),
    get: vi.fn(async () => undefined),
    delete: vi.fn(async () => undefined),
    post: vi.fn(async () => undefined),
    put: vi.fn(async () => undefined),
    patch: vi.fn(async () => undefined),
    interceptors: {
      request: { use: vi.fn(), eject: vi.fn(), clear: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn(), clear: vi.fn() },
    },
  }
}
