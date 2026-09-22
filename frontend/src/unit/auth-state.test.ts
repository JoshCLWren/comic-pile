import { 
  isDefinitiveAuthenticationFailure, 
  isServiceUnavailable, 
  isNetworkError, 
  createAuthError,
  calculateRetryDelay,
} from '../services/authState'

describe('Auth State Service', () => {
  describe('isDefinitiveAuthenticationFailure', () => {
    it('returns true for 401 errors', () => {
      const error = new Error('Unauthorized') as any
      error.response = { status: 401 }
      expect(isDefinitiveAuthenticationFailure(error)).toBe(true)
    })

    it('returns false for non-401 errors', () => {
      const error = new Error('Service Unavailable') as any
      error.response = { status: 503 }
      expect(isDefinitiveAuthenticationFailure(error)).toBe(false)
    })

    it('returns false for non-Axios errors', () => {
      const error = new Error('Network error')
      expect(isDefinitiveAuthenticationFailure(error)).toBe(false)
    })
  })

  describe('isServiceUnavailable', () => {
    it('returns true for 503 errors', () => {
      const error = new Error('Service Unavailable') as any
      error.response = { status: 503 }
      expect(isServiceUnavailable(error)).toBe(true)
    })

    it('returns true for timeout errors', () => {
      const error = new Error('Timeout') as any
      error.code = 'ECONNABORTED'
      expect(isServiceUnavailable(error)).toBe(true)
    })

    it('returns false for other errors', () => {
      const error = new Error('Network error') as any
      error.response = { status: 500 }
      expect(isServiceUnavailable(error)).toBe(false)
    })
  })

  describe('isNetworkError', () => {
    it('returns true for network errors without response', () => {
      const error = new Error('Network error') as any
      expect(isNetworkError(error)).toBe(true)
    })

    it('returns true for ERR_NETWORK errors', () => {
      const error = new Error('Network error') as any
      error.code = 'ERR_NETWORK'
      expect(isNetworkError(error)).toBe(true)
    })

    it('returns false for errors with response', () => {
      const error = new Error('Service error') as any
      error.response = { status: 500 }
      expect(isNetworkError(error)).toBe(false)
    })
  })

  describe('createAuthError', () => {
    it('creates definitive auth failure error for 401', () => {
      const error = new Error('Unauthorized') as any
      error.response = { status: 401 }
      
      const authError = createAuthError(error)
      expect(authError).toEqual({
        type: 'definitive_auth_failure',
        message: 'Authentication failed. Please login again.',
        status: 401,
      })
    })

    it('creates service unavailable error for 503', () => {
      const error = new Error('Service Unavailable') as any
      error.response = { status: 503 }
      
      const authError = createAuthError(error)
      expect(authError).toEqual({
        type: 'service_unavailable',
        message: 'ComicPile is temporarily unavailable',
        status: 503,
      })
    })

    it('creates network error for network failures', () => {
      const error = new Error('Network error') as any
      
      const authError = createAuthError(error)
      expect(authError).toEqual({
        type: 'network',
        message: "Can't reach ComicPile",
      })
    })

    it('returns null for unknown error types', () => {
      const error = new Error('Unknown error') as any
      error.response = { status: 500 }
      
      const authError = createAuthError(error)
      expect(authError).toBe(null)
    })
  })

  describe('calculateRetryDelay', () => {
    it('calculates exponential backoff with jitter', () => {
      const delay1 = calculateRetryDelay(1, 1000)
      const delay2 = calculateRetryDelay(2, 1000)
      const delay3 = calculateRetryDelay(3, 1000)
      
      // Should be approximately 1000ms, 2000ms, 4000ms with jitter
      expect(delay1).toBeGreaterThan(900)
      expect(delay1).toBeLessThan(1100)
      expect(delay2).toBeGreaterThan(1800)
      expect(delay2).toBeLessThan(2200)
      expect(delay3).toBeGreaterThan(3600)
      expect(delay3).toBeLessThan(4400)
    })

    it('caps delay at 30000ms', () => {
      const delay = calculateRetryDelay(10, 10000) // Would be 512000ms without cap
      expect(delay).toBeLessThanOrEqual(30000)
    })

    it('includes random jitter', () => {
      // Run multiple times to check for variation
      const delays = Array.from({ length: 10 }, () => calculateRetryDelay(1, 1000))
      const hasVariation = new Set(delays).size > 1
      expect(hasVariation).toBe(true)
    })
  })
})