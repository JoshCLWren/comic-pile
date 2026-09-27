import { vi, type Mock } from 'vitest'
import type { AxiosRequestConfig } from 'axios'

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
  // SAFETY: test double satisfies TransportDouble and minimally AxiosInstance for interceptor registration.
  // Avoid chained type assertions by constructing the object with the correct type upfront.
  const double: TransportDouble & { interceptors: { request: { use: Mock }; response: { use: Mock } } } = {
    request: vi.fn(async () => undefined) as Mock,
    get: vi.fn(async () => undefined) as Mock,
    post: vi.fn(async () => undefined) as Mock,
    put: vi.fn(async () => undefined) as Mock,
    delete: vi.fn(async () => undefined) as Mock,
    patch: vi.fn(async () => undefined) as Mock,
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }
  // SAFETY: constructed object satisfies TransportDouble; AxiosInstance compatibility is only needed for test wiring.
  return double as TransportDouble
}
