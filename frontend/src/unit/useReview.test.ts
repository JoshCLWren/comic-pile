import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API service
const reviewsApiMock = vi.hoisted(() => ({
  listReviews: vi.fn(),
  getThreadReviews: vi.fn(),
  getReview: vi.fn(),
  createOrUpdateReview: vi.fn(),
  updateReview: vi.fn(),
  deleteReview: vi.fn(),
}))

vi.mock('../services/api-reviews', () => ({
  reviewsApi: reviewsApiMock,
}))

// Mock the getApiErrorDetail utility
vi.mock('../utils/apiError', () => ({
  getApiErrorDetail: vi.fn((error) => error?.message || 'Unknown error'),
}))

import { 
  useReviews, 
  useThreadReviews, 
  useReview, 
  useCreateOrUpdateReview, 
  useUpdateReview, 
  useDeleteReview 
} from '../hooks/useReview'
import type { Review, ReviewCreatePayload, ReviewUpdatePayload } from '../types'

const mockReview: Review = {
  id: 1,
  user_id: 1,
  thread_id: 42,
  rating: 4.5,
  review_text: 'Great issue!',
  issue_id: 1,
  issue_number: '1',
  thread_title: 'Test Thread',
  thread_format: 'issue',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

describe('useReviews', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useReviews())

    expect(result.current.reviews).toEqual([])
    expect(result.current.nextPageToken).toBeNull()
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('should fetch reviews successfully', async () => {
    const mockResponse = {
      reviews: [mockReview],
      next_page_token: 'next-page-token',
    }

    reviewsApiMock.listReviews.mockResolvedValue(mockResponse)

    const { result } = renderHook(() => useReviews())

    await act(async () => {
      await result.current.list()
    })

    await waitFor(() => {
      expect(result.current.reviews).toEqual([mockReview])
      expect(result.current.nextPageToken).toBe('next-page-token')
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(false)
    })

    expect(reviewsApiMock.listReviews).toHaveBeenCalledWith(undefined)
  })

  it('should fetch reviews with pagination params', async () => {
    const mockResponse = {
      reviews: [mockReview],
      next_page_token: null,
    }

    reviewsApiMock.listReviews.mockResolvedValue(mockResponse)

    const { result } = renderHook(() => useReviews())

    await act(async () => {
      await result.current.list({ page_size: 10, page_token: 'abc123' })
    })

    expect(reviewsApiMock.listReviews).toHaveBeenCalledWith({ page_size: 10, page_token: 'abc123' })
  })

  it('should handle API errors', async () => {
    const error = new Error('Failed to fetch reviews')
    reviewsApiMock.listReviews.mockRejectedValue(error)

    const { result } = renderHook(() => useReviews())

    let thrownError: Error | null = null
    await act(async () => {
      try {
        await result.current.list()
      } catch (err) {
        thrownError = err as Error
      }
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(true)
      expect(thrownError).toBe(error)
    })
  })
})

describe('useThreadReviews', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useThreadReviews())

    expect(result.current.reviews).toEqual([])
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('should fetch thread reviews successfully', async () => {
    const threadReviews = [mockReview]
    reviewsApiMock.getThreadReviews.mockResolvedValue(threadReviews)

    const { result } = renderHook(() => useThreadReviews())

    await act(async () => {
      await result.current.getThreadReviews(42)
    })

    await waitFor(() => {
      expect(result.current.reviews).toEqual(threadReviews)
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(false)
    })

    expect(reviewsApiMock.getThreadReviews).toHaveBeenCalledWith(42)
  })

  it('should not fetch when threadId is null', async () => {
    const { result } = renderHook(() => useThreadReviews())

    await act(async () => {
      await result.current.getThreadReviews(0)
    })

    expect(reviewsApiMock.getThreadReviews).not.toHaveBeenCalled()
  })

  it('should handle API errors', async () => {
    const error = new Error('Failed to fetch thread reviews')
    reviewsApiMock.getThreadReviews.mockRejectedValue(error)

    const { result } = renderHook(() => useThreadReviews())

    let thrownError: Error | null = null
    await act(async () => {
      try {
        await result.current.getThreadReviews(42)
      } catch (err) {
        thrownError = err as Error
      }
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(true)
      expect(thrownError).toBe(error)
    })
  })
})

describe('useReview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useReview())

    expect(result.current.review).toBeNull()
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('should fetch review successfully', async () => {
    reviewsApiMock.getReview.mockResolvedValue(mockReview)

    const { result } = renderHook(() => useReview())

    await act(async () => {
      await result.current.getReview(1)
    })

    await waitFor(() => {
      expect(result.current.review).toEqual(mockReview)
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(false)
    })

    expect(reviewsApiMock.getReview).toHaveBeenCalledWith(1)
  })

  it('should not fetch when review id is null', async () => {
    const { result } = renderHook(() => useReview())

    await act(async () => {
      await result.current.getReview(0)
    })

    expect(reviewsApiMock.getReview).not.toHaveBeenCalled()
  })

  it('should handle API errors', async () => {
    const error = new Error('Failed to fetch review')
    reviewsApiMock.getReview.mockRejectedValue(error)

    const { result } = renderHook(() => useReview())

    let thrownError: Error | null = null
    await act(async () => {
      try {
        await result.current.getReview(1)
      } catch (err) {
        thrownError = err as Error
      }
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(true)
      expect(thrownError).toBe(error)
    })
  })
})

describe('useCreateOrUpdateReview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useCreateOrUpdateReview())

    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('should create review successfully', async () => {
    const reviewData: ReviewCreatePayload = {
      thread_id: 42,
      rating: 4.5,
      issue_number: '1',
      review_text: 'Great issue!',
    }

    reviewsApiMock.createOrUpdateReview.mockResolvedValue(mockReview)

    const { result } = renderHook(() => useCreateOrUpdateReview())

    let createdReview: Review | null = null
    await act(async () => {
      createdReview = await result.current.createOrUpdateReview(reviewData)
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(false)
    })

    expect(createdReview).toEqual(mockReview)
    expect(reviewsApiMock.createOrUpdateReview).toHaveBeenCalledWith(reviewData)
  })

  it('should handle API errors', async () => {
    const reviewData: ReviewCreatePayload = {
      thread_id: 42,
      rating: 4.5,
    }

    const error = new Error('Failed to create review')
    reviewsApiMock.createOrUpdateReview.mockRejectedValue(error)

    const { result } = renderHook(() => useCreateOrUpdateReview())

    let thrownError: Error | null = null
    await act(async () => {
      try {
        await result.current.createOrUpdateReview(reviewData)
      } catch (err) {
        thrownError = err as Error
      }
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(true)
      expect(thrownError).toBe(error)
    })
  })
})

describe('useUpdateReview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useUpdateReview())

    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('should update review successfully', async () => {
    const updateData: ReviewUpdatePayload = {
      review_text: 'Updated review content',
    }

    const updatedReview = { ...mockReview, review_text: 'Updated review content' }
    reviewsApiMock.updateReview.mockResolvedValue(updatedReview)

    const { result } = renderHook(() => useUpdateReview())

    let returnedReview: Review | null = null
    await act(async () => {
      returnedReview = await result.current.updateReview(1, updateData)
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(false)
    })

    expect(returnedReview).toEqual(updatedReview)
    expect(reviewsApiMock.updateReview).toHaveBeenCalledWith(1, updateData)
  })

  it('should handle API errors', async () => {
    const updateData: ReviewUpdatePayload = {
      review_text: 'Updated review content',
    }

    const error = new Error('Failed to update review')
    reviewsApiMock.updateReview.mockRejectedValue(error)

    const { result } = renderHook(() => useUpdateReview())

    let thrownError: Error | null = null
    await act(async () => {
      try {
        await result.current.updateReview(1, updateData)
      } catch (err) {
        thrownError = err as Error
      }
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(true)
      expect(thrownError).toBe(error)
    })
  })
})

describe('useDeleteReview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useDeleteReview())

    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
  })

  it('should delete review successfully', async () => {
    reviewsApiMock.deleteReview.mockResolvedValue(undefined)

    const { result } = renderHook(() => useDeleteReview())

    await act(async () => {
      await result.current.deleteReview(1)
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(false)
    })

    expect(reviewsApiMock.deleteReview).toHaveBeenCalledWith(1)
  })

  it('should handle API errors', async () => {
    const error = new Error('Failed to delete review')
    reviewsApiMock.deleteReview.mockRejectedValue(error)

    const { result } = renderHook(() => useDeleteReview())

    let thrownError: Error | null = null
    await act(async () => {
      try {
        await result.current.deleteReview(1)
      } catch (err) {
        thrownError = err as Error
      }
    })

    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
      expect(result.current.isError).toBe(true)
      expect(thrownError).toBe(error)
    })
  })
})