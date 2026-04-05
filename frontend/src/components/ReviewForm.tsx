import { useState, useEffect } from 'react'
import Modal from '../components/Modal'
import type { Review, ReviewCreatePayload } from '../types'

interface ReviewFormProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (review: ReviewCreatePayload) => Promise<void>
  threadId: number
  threadTitle: string
  issueNumber?: string
  rating: number
  existingReview?: Review | null
  error?: string | null
}

export default function ReviewForm({
  isOpen,
  onClose,
  onSubmit,
  threadId,
  threadTitle,
  issueNumber,
  rating,
  existingReview,
  error,
}: ReviewFormProps) {
  const [reviewText, setReviewText] = useState(existingReview?.review_text || '')
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setReviewText(existingReview?.review_text || '')
      setIsSubmitting(false)
    }
  }, [isOpen, existingReview])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSubmitting(true)

    try {
      const reviewData: ReviewCreatePayload = {
        thread_id: threadId,
        rating,
        review_text: reviewText.trim() || undefined,
        ...(issueNumber && { issue_number: issueNumber }),
      }

      await onSubmit(reviewData)
      setReviewText('')
      onClose()
    } catch (error) {
      console.error('Failed to submit review:', error)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSkip = async () => {
    setReviewText('')
    setIsSubmitting(true)
    try {
      const reviewData: ReviewCreatePayload = {
        thread_id: threadId,
        rating,
        ...(issueNumber && { issue_number: issueNumber }),
      }
      await onSubmit(reviewData)
      onClose()
    } catch (error) {
      console.error('Failed to submit rating:', error)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      title={existingReview ? 'Edit Review' : 'Write a Review?'}
      onClose={onClose}
      overlayClassName="review-modal__overlay"
      data-testid="modal"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}
        <div className="space-y-2">
          <p className="text-sm text-stone-300">
            {issueNumber
              ? `Reviewing ${threadTitle} #${issueNumber}`
              : `Reviewing ${threadTitle}`
            }
          </p>
          <div className="flex items-center gap-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">Rating:</span>
            <span className="text-lg font-black text-amber-400">{rating.toFixed(1)}</span>
          </div>
        </div>

        <div className="space-y-2">
          <label htmlFor="review-text" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            Your Review (Optional)
          </label>
          <textarea
            id="review-text"
            value={reviewText}
            onChange={(e) => setReviewText(e.target.value)}
            placeholder="Share your thoughts about this comic..."
            className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300 min-h-[120px] resize-y focus:outline-none focus:ring-2 focus:ring-amber-500/50"
            maxLength={2000}
          />
          <div className="text-[10px] text-stone-500 text-right">
            {reviewText.length}/2000 characters
          </div>
        </div>

        <div className="space-y-3 pt-2">
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={handleSkip}
              disabled={isSubmitting}
              className="w-full py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all disabled:opacity-50"
            >
              Skip
            </button>
            <button
              type="submit"
              disabled={isSubmitting || (!reviewText.trim() && !existingReview)}
              className="w-full py-3 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/50 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all disabled:opacity-50"
            >
              {isSubmitting ? 'Saving...' : (existingReview ? 'Update Review' : 'Save Review')}
            </button>
          </div>

          {existingReview && (
            <button
              type="button"
              onClick={() => {
                setReviewText('')
                onClose()
              }}
              disabled={isSubmitting}
              className="w-full py-2 text-[10px] text-stone-500 hover:text-stone-300 transition-colors"
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </Modal>
  )
}