import { defaultHttpClient, type HttpClient } from './httpClient'

export interface ForgotPasswordRequest {
  email: string
}

export interface ResetPasswordRequest {
  token: string
  new_password: string
}

export interface PasswordResetResponse {
  message: string
}

/**
 * Build the password-reset service bound to an HTTP client.
 *
 * Both paths carry single-use secrets, so the transport in `api.ts` enumerates
 * them in `AUTH_ENDPOINT_PATHS` and `SENSITIVE_AUTH_BODY_PATHS` to skip CSRF
 * attachment and redact the request body from error logging.
 *
 * @param client - HTTP transport used for every password-reset request.
 * @returns The password-reset API bound to `client`.
 */
export function createAuthApi(client: HttpClient) {
  return {
    forgotPassword: (data: ForgotPasswordRequest) =>
      client.post<PasswordResetResponse, ForgotPasswordRequest>('/v1/auth/forgot-password', data),
    resetPassword: (data: ResetPasswordRequest) =>
      client.post<PasswordResetResponse, ResetPasswordRequest>('/v1/auth/reset-password', data),
  }
}

export const authApi = createAuthApi(defaultHttpClient())
