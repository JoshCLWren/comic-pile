import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API service
const bugReportsApiMock = vi.hoisted(() => ({
  create: vi.fn(),
}))

vi.mock('../services/api', () => ({
  bugReportsApi: bugReportsApiMock,
  default: {},
}))

// Mock the getApiErrorDetail utility
vi.mock('../utils/apiError', () => ({
  getApiErrorDetail: vi.fn((error) => error?.message || 'Unknown error'),
}))

import { useBugReport } from '../hooks/useBugReport'

describe('useBugReport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useBugReport())

    expect(result.current.isSubmitting).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.issueUrl).toBeNull()
  })

  it('should set isSubmitting during submission', async () => {
    bugReportsApiMock.create.mockReturnValue(new Promise(() => {}))

    const { result } = renderHook(() => useBugReport())

    act(() => {
      result.current.submit('Test title', 'Test description', null)
    })

    expect(result.current.isSubmitting).toBe(true)
  })

  it('should set issueUrl on success', async () => {
    const mockResponse = { issue_url: 'https://github.com/test/issues/1' }
    bugReportsApiMock.create.mockResolvedValue(mockResponse)

    const { result } = renderHook(() => useBugReport())

    await act(async () => {
      await result.current.submit('Test title', 'Test description', null)
    })

    await waitFor(() => {
      expect(result.current.issueUrl).toBe('https://github.com/test/issues/1')
      expect(result.current.isSubmitting).toBe(false)
      expect(result.current.error).toBeNull()
    })
  })

  it('should set error on failure', async () => {
    const error = new Error('GitHub API error')
    bugReportsApiMock.create.mockRejectedValue(error)

    const { result } = renderHook(() => useBugReport())

    let thrownError: Error | null = null
    await act(async () => {
      try {
        await result.current.submit('Test title', 'Test description', null)
      } catch (err) {
        thrownError = err as Error
      }
    })

    await waitFor(() => {
      expect(result.current.error).toBe('GitHub API error')
      expect(result.current.isSubmitting).toBe(false)
      expect(result.current.issueUrl).toBeNull()
      expect(thrownError).toBe(error)
    })
  })

  it('should include screenshot in FormData when provided', async () => {
    const mockResponse = { issue_url: 'https://github.com/test/issues/1' }
    bugReportsApiMock.create.mockResolvedValue(mockResponse)

    const { result } = renderHook(() => useBugReport())

    const blob = new Blob(['test'], { type: 'image/png' })

    await act(async () => {
      await result.current.submit('Test title', 'Test description', blob)
    })

    expect(bugReportsApiMock.create).toHaveBeenCalledWith(expect.any(FormData))
    const formDataCall = bugReportsApiMock.create.mock.calls[0][0] as FormData
    const screenshot = formDataCall.get('screenshot') as File
    expect(screenshot).toBeInstanceOf(File)
    expect(screenshot.name).toBe('screenshot.png')
    expect(screenshot.type).toBe('image/png')
  })

  it('should not include screenshot in FormData when null', async () => {
    const mockResponse = { issue_url: 'https://github.com/test/issues/1' }
    bugReportsApiMock.create.mockResolvedValue(mockResponse)

    const { result } = renderHook(() => useBugReport())

    await act(async () => {
      await result.current.submit('Test title', 'Test description', null)
    })

    expect(bugReportsApiMock.create).toHaveBeenCalledWith(expect.any(FormData))
    const formDataCall = bugReportsApiMock.create.mock.calls[0][0] as FormData
    expect(formDataCall.get('screenshot')).toBeNull()
  })

  it('should reset error and issueUrl on reset()', async () => {
    const error = new Error('GitHub API error')
    bugReportsApiMock.create.mockRejectedValue(error)

    const { result } = renderHook(() => useBugReport())

    await act(async () => {
      try {
        await result.current.submit('Test title', 'Test description', null)
      } catch {
        // Expected error
      }
    })

    await waitFor(() => {
      expect(result.current.error).not.toBeNull()
    })

    act(() => {
      result.current.reset()
    })

    expect(result.current.error).toBeNull()
    expect(result.current.issueUrl).toBeNull()
  })
})
