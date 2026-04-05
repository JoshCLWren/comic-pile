import { useState, useCallback } from 'react'
import { reviewsApi } from '../services/api-reviews'
import { getApiErrorDetail } from '../utils/apiError'
import type { Review, ReviewCreatePayload, ReviewUpdatePayload } from '../types'

export function useReviews() {
  const [reviews, setReviews] = useState<Review[]>([])
  const [nextPageToken, setNextPageToken] = useState<string | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const list = async (params?: { page_size?: number; page_token?: string | null }) => {
    setIsPending(true)
    setIsError(false)
    try {
      const response = await reviewsApi.listReviews(params)
      setReviews(response.reviews)
      setNextPageToken(response.next_page_token || null)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to fetch reviews:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { reviews, nextPageToken, list, isPending, isError }
}

export function useThreadReviews() {
  const [reviews, setReviews] = useState<Review[]>([])
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const getThreadReviews = useCallback(async (threadId: number) => {
    if (!threadId) return
    setIsPending(true)
    setIsError(false)
    try {
      const reviews = await reviewsApi.getThreadReviews(threadId)
      setReviews(reviews)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to fetch thread reviews:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { reviews, getThreadReviews, isPending, isError }
}

export function useReview() {
  const [review, setReview] = useState<Review | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const getReview = async (id: number | null) => {
    if (!id) return
    setIsPending(true)
    setIsError(false)
    try {
      const review = await reviewsApi.getReview(id)
      setReview(review)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to fetch review:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { review, getReview, isPending, isError }
}

export function useCreateOrUpdateReview() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const createOrUpdateReview = async (data: ReviewCreatePayload) => {
    setIsPending(true)
    setIsError(false)
    try {
      const review = await reviewsApi.createOrUpdateReview(data)
      return review
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to create/update review:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { createOrUpdateReview, isPending, isError }
}

export function useUpdateReview() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const updateReview = async (id: number, data: ReviewUpdatePayload) => {
    setIsPending(true)
    setIsError(false)
    try {
      const review = await reviewsApi.updateReview(id, data)
      return review
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to update review:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { updateReview, isPending, isError }
}

export function useDeleteReview() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const deleteReview = async (id: number) => {
    setIsPending(true)
    setIsError(false)
    try {
      await reviewsApi.deleteReview(id)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to delete review:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { deleteReview, isPending, isError }
}