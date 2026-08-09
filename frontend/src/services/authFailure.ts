import axios from 'axios'

/** Return true only when the server has definitively rejected the persistent session. */
export function isDefinitiveAuthenticationFailure(error: unknown): boolean {
  if (!axios.isAxiosError(error)) {
    return false
  }

  return error.response?.status === 401
}
