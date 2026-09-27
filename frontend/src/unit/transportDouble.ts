import { vi, type Mock } from 'vitest'
import type { AxiosInstance } from 'axios'

/**
 * Faithful in-test stand-in for the axios instance the API client wraps.
 *
 * It records every request and captures the interceptors `createApiClient`
 * registers, so tests exercise the real client wiring and interceptor pipeline
 * instead of replacing a module.
 */
export interface TransportDouble {
  request: Mock
  get: Mock
  post: Mock
  put: Mock
  delete: Mock
  patch: Mock
  interceptors: {
    request: { use: Mock }
    response: { use: Mock }
  }
}

/**
 * Build a fresh {@link TransportDouble}.
 *
 * @returns A transport double whose request methods resolve to `undefined`.
 */
export function createTransportDouble(): TransportDouble {
  return {
    request: vi.fn(),
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  } as unknown as TransportDouble & AxiosInstance
}
