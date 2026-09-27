import type { AxiosRequestConfig } from 'axios'

/**
 * Per-request configuration accepted by the service layer.
 *
 * Mirrors the real transport's request options so the production axios-backed
 * client satisfies {@link HttpClient} without a cast at the wiring site.
 */
export type HttpRequestConfig<D = unknown> = AxiosRequestConfig<D> & {
  skipAuthRedirect?: boolean
}

/**
 * Minimal HTTP client contract shared by the service layer.
 *
 * Every service factory accepts this interface instead of importing the
 * axios-backed singleton directly. Production wiring passes the real client
 * from `./api`; tests pass a faithful in-test double that records calls and
 * returns canned payloads. This keeps the service seam a real interface
 * rather than a module-level mock target.
 */
export interface HttpClient {
  request<T = unknown, D = unknown>(config: HttpRequestConfig<D>): Promise<T>
  get<T = unknown>(url: string, config?: HttpRequestConfig): Promise<T>
  delete<T = unknown>(url: string, config?: HttpRequestConfig): Promise<T>
  head<T = unknown>(url: string, config?: HttpRequestConfig): Promise<T>
  post<T = unknown, D = unknown>(url: string, data?: D, config?: HttpRequestConfig<D>): Promise<T>
  put<T = unknown, D = unknown>(url: string, data?: D, config?: HttpRequestConfig<D>): Promise<T>
  patch<T = unknown, D = unknown>(url: string, data?: D, config?: HttpRequestConfig<D>): Promise<T>
}
