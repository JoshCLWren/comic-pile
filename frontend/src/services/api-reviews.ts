import type { AxiosRequestConfig } from 'axios'
import api from './api'
import type { Review, ReviewCreatePayload, ReviewUpdatePayload, ReviewListResponse } from '../types'

export const reviewsApi = {
  /**
   * Create a new review or update existing review.
   * Users can have one review per thread/issue combination.
   */
  createOrUpdateReview: (data: ReviewCreatePayload) =>
    api.post<Review, ReviewCreatePayload>('/v1/reviews/', data),

  /**
   * List reviews for current user with pagination.
   */
  listReviews: async (params?: { page_size?: number; page_token?: string | null }) => {
    const queryParams = {
      page_size: params?.page_size || 20,
      ...(params?.page_token ? { page_token: params.page_token } : {}),
    }
    const response = await api.get<ReviewListResponse>('/v1/reviews/', {
      params: Object.keys(queryParams).length ? queryParams : undefined,
    })
    return response
  },

  /**
   * Get a specific review.
   */
  getReview: (id: number) => api.get<Review>(`/v1/reviews/${id}`),

  /**
   * Update an existing review.
   */
  updateReview: (id: number, data: ReviewUpdatePayload) =>
    api.put<Review, ReviewUpdatePayload>(`/v1/reviews/${id}`, data),

  /**
   * Delete a review.
   */
  deleteReview: (id: number) => api.delete<void>(`/v1/reviews/${id}`),

  /**
   * Get all reviews for a specific thread.
   */
  getThreadReviews: (threadId: number) =>
    api.get<Review[]>(`/threads/${threadId}/reviews`),
}