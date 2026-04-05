import { beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
}))

const { get, post, put } = apiMock
const del = apiMock.delete

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock),
  },
}))

import { reviewsApi } from '../services/api-reviews'

beforeEach(() => {
  get.mockResolvedValue({})
  post.mockResolvedValue({})
  put.mockResolvedValue({})
  del.mockResolvedValue({})
})

it('calls list reviews endpoint with expected paths', () => {
  reviewsApi.listReviews()
  reviewsApi.listReviews({ page_size: 10, page_token: 'abc123' })

  expect(get).toHaveBeenCalledWith('/v1/reviews/', { params: { page_size: 20 } })
  expect(get).toHaveBeenCalledWith('/v1/reviews/', { params: { page_size: 10, page_token: 'abc123' } })
})

it('calls get thread reviews endpoint with expected paths', () => {
  reviewsApi.getThreadReviews(42)

  expect(get).toHaveBeenCalledWith('/v1/reviews/threads/42/reviews')
})

it('calls get review endpoint with expected paths', () => {
  reviewsApi.getReview(123)

  expect(get).toHaveBeenCalledWith('/v1/reviews/123')
})

it('calls create or update review endpoint with expected data', () => {
  const reviewData = {
    thread_id: 42,
    rating: 4.5,
    issue_number: '1',
    review_text: 'Great issue!',
  }

  reviewsApi.createOrUpdateReview(reviewData)

  expect(post).toHaveBeenCalledWith('/v1/reviews/', reviewData)
})

it('calls update review endpoint with expected data', () => {
  const updateData = {
    review_text: 'Updated review content',
  }

  reviewsApi.updateReview(123, updateData)

  expect(put).toHaveBeenCalledWith('/v1/reviews/123', updateData)
})

it('calls delete review endpoint with expected paths', () => {
  reviewsApi.deleteReview(123)

  expect(del).toHaveBeenCalledWith('/v1/reviews/123')
})