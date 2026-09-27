import type { AxiosRequestConfig } from 'axios'

/**
 * Request configuration accepted by {@link HttpClient}.
 *
 * `skipAuthRedirect` lets a caller suppress the login redirect while the client
 * recovers a session, and `_retry` keeps a retried request from refreshing again.
 */
export type ApiRequestConfig<D = unknown> = AxiosRequestConfig<D> & {
  _retry?: boolean
  _queued?: boolean
  skipAuthRedirect?: boolean
}

/**
 * Outgoing HTTP transport the service layer depends on.
 *
 * Service factories take this contract instead of the concrete axios instance,
 * so production keeps the real interceptor pipeline while tests can supply a
 * faithful double. Every method returns a payload: the API client registers an
 * interceptor that unwraps `response.data` before the promise settles.
 */
export interface HttpClient {
  get<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  delete<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  post<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  put<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  patch<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
}

let registeredHttpClient: HttpClient | null = null

/**
 * Register the transport the default service singletons send through.
 *
 * `api.ts` is the composition root, so it registers the real interceptor-backed
 * client once module evaluation finishes.
 *
 * @param client - The transport every default service must use.
 */
export function setDefaultHttpClient(client: HttpClient): void {
  registeredHttpClient = client
}

/**
 * Resolve the registered default transport.
 *
 * @returns The transport registered by {@link setDefaultHttpClient}.
 */
function resolveDefaultHttpClient(): HttpClient {
  if (!registeredHttpClient) {
    throw new Error('The default HTTP client was requested before api.ts registered one')
  }
  return registeredHttpClient
}

/**
 * Build the transport the default service singletons are bound to.
 *
 * Service modules are evaluated as dependencies of `api.ts`, so binding the
 * real client while they load would read it before it exists. This transport
 * forwards every call to the registered client instead, so the binding happens
 * on first use no matter what order the bundler emits the modules in.
 *
 * @returns A transport that resolves the default client per request.
 */
export function defaultHttpClient(): HttpClient {
  return {
    get: (url, config) => resolveDefaultHttpClient().get(url, config),
    delete: (url, config) => resolveDefaultHttpClient().delete(url, config),
    post: (url, data, config) => resolveDefaultHttpClient().post(url, data, config),
    put: (url, data, config) => resolveDefaultHttpClient().put(url, data, config),
    patch: (url, data, config) => resolveDefaultHttpClient().patch(url, data, config),
  }
}
