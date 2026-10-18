import { describe, expect, it } from 'vitest'
import { getApiErrorDetail, getApiErrorStatus, isIndeterminateApiOutcome } from '../utils/apiError'

describe('getApiErrorDetail', () => {
  it('extracts detail from Axios error response', () => {
    const error = {
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: 'Thread not found' },
      },
      message: 'Request failed',
    }
    expect(getApiErrorDetail(error)).toBe('Thread not found')
  })

  it('returns message for Axios error without detail', () => {
    const error = {
      isAxiosError: true,
      response: {
        status: 500,
        data: {},
      },
      message: 'Internal server error',
    }
    expect(getApiErrorDetail(error)).toBe('Internal server error')
  })

  it('returns Unknown error for Axios errors without detail or a message', () => {
    const error = {
      isAxiosError: true,
      response: {
        status: 500,
        data: {},
      },
    }
    expect(getApiErrorDetail(error)).toBe('Unknown error')
  })

  it('handles network errors with Axios', () => {
    const error = {
      isAxiosError: true,
      response: undefined,
      message: 'Network Error',
    }
    expect(getApiErrorDetail(error)).toBe('Network error. Please check your connection.')
  })

  it('handles fetch failures with Axios', () => {
    const error = {
      isAxiosError: true,
      response: undefined,
      message: 'Failed to fetch',
    }
    expect(getApiErrorDetail(error)).toBe('Network error. Please check your connection.')
  })

  it('handles network request failures with Axios', () => {
    const error = {
      isAxiosError: true,
      response: undefined,
      message: 'Network request failed',
    }
    expect(getApiErrorDetail(error)).toBe('Network error. Please check your connection.')
  })

  it('handles generic error objects', () => {
    const error = {
      response: {
        status: 404,
        data: { detail: 'Not found' },
      },
    }
    expect(getApiErrorDetail(error)).toBe('Not found')
  })

  it('returns Unknown error for generic response objects without detail', () => {
    const error = {
      response: {
        status: 500,
        data: {},
      },
    }
    expect(getApiErrorDetail(error)).toBe('Unknown error')
  })

  it('returns Unknown error for objects without response', () => {
    const error = { some: 'object' }
    expect(getApiErrorDetail(error)).toBe('Unknown error')
  })

  it('extracts detail from an Error instance carrying a response', () => {
    const error = Object.assign(new Error('Request failed'), {
      response: { status: 409, data: { detail: 'No pending roll to skip. Roll first.' } },
    })
    expect(getApiErrorDetail(error)).toBe('No pending roll to skip. Roll first.')
  })

  it('handles Error instances', () => {
    const error = new Error('Something went wrong')
    expect(getApiErrorDetail(error)).toBe('Something went wrong')
  })

  it('handles Error instances with network error message', () => {
    const error = new Error('Network Error')
    expect(getApiErrorDetail(error)).toBe('Network error. Please check your connection.')
  })

  it('handles null/undefined', () => {
    expect(getApiErrorDetail(null)).toBe('Unknown error')
    expect(getApiErrorDetail(undefined)).toBe('Unknown error')
  })
})

describe('getApiErrorStatus', () => {
  it('extracts status from Axios error', () => {
    const error = {
      isAxiosError: true,
      response: {
        status: 404,
        data: {},
      },
    }
    expect(getApiErrorStatus(error)).toBe(404)
  })

  it('returns null for Axios error without response', () => {
    const error = {
      isAxiosError: true,
      response: undefined,
    }
    expect(getApiErrorStatus(error)).toBe(null)
  })

  it('extracts status from generic error object', () => {
    const error = {
      response: {
        status: 500,
        data: {},
      },
    }
    expect(getApiErrorStatus(error)).toBe(500)
  })

  it('extracts status from an Error instance carrying a response', () => {
    const error = Object.assign(new Error('Request failed'), {
      response: { status: 409, data: { detail: 'pending' } },
    })
    expect(getApiErrorStatus(error)).toBe(409)
  })

  it('returns null for error without response', () => {
    const error = new Error('Something went wrong')
    expect(getApiErrorStatus(error)).toBe(null)
  })

  it('returns null for null/undefined', () => {
    expect(getApiErrorStatus(null)).toBe(null)
    expect(getApiErrorStatus(undefined)).toBe(null)
  })
})

describe('isIndeterminateApiOutcome', () => {
  it('treats a 4xx refusal as definitive', () => {
    const error = {
      isAxiosError: true,
      response: { status: 422, data: { detail: 'invalid_approved_row' } },
    }
    expect(isIndeterminateApiOutcome(error)).toBe(false)
  })

  it('treats a 5xx response as indeterminate', () => {
    const error = {
      isAxiosError: true,
      response: { status: 502, data: {} },
      message: 'Bad Gateway',
    }
    expect(isIndeterminateApiOutcome(error)).toBe(true)
  })

  it('treats an axios transport failure without a response as indeterminate', () => {
    const error = {
      isAxiosError: true,
      response: undefined,
      message: 'timeout of 10000ms exceeded',
    }
    expect(isIndeterminateApiOutcome(error)).toBe(true)
  })

  it('treats a generic network error message as indeterminate', () => {
    expect(isIndeterminateApiOutcome(new Error('Network Error'))).toBe(true)
    expect(isIndeterminateApiOutcome(new Error('Failed to fetch'))).toBe(true)
  })

  it('treats an unrelated client-side error as definitive', () => {
    expect(isIndeterminateApiOutcome(new Error('Server error'))).toBe(false)
    expect(isIndeterminateApiOutcome(null)).toBe(false)
    expect(isIndeterminateApiOutcome(undefined)).toBe(false)
  })

  it('reads status from an Error instance carrying a response', () => {
    const error = Object.assign(new Error('Request failed'), {
      response: { status: 503, data: {} },
    })
    expect(isIndeterminateApiOutcome(error)).toBe(true)
  })
})