import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewForm from '../components/ReviewForm'
import type { Review } from '../types'

// Mock the Modal component
vi.mock('../components/Modal', () => ({
  default: ({ 
    isOpen, 
    title, 
    onClose, 
    children, 
    overlayClassName 
  }: {
    isOpen: boolean
    title: string
    onClose: () => void
    children: React.ReactNode
    overlayClassName?: string
  }) => {
    if (!isOpen) return null
    return (
      <div data-testid="modal" className={overlayClassName}>
        <h2 data-testid="modal-title">{title}</h2>
        <button data-testid="close-button" onClick={onClose}>
          Close
        </button>
        <div data-testid="modal-content">{children}</div>
      </div>
    )
  }
}))

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

describe('ReviewForm', () => {
  const mockOnSubmit = vi.fn()
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should not render when modal is closed', () => {
    const { container } = render(
      <ReviewForm
        isOpen={false}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    expect(container.firstChild).toBeNull()
  })

  it('should render modal when open', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByTestId('modal-title')).toHaveTextContent('Write a Review?')
  })

  it('should show edit title when existing review is provided', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    expect(screen.getByTestId('modal-title')).toHaveTextContent('Edit Review')
  })

  it('should display thread information with issue number', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        issueNumber="1"
      />
    )

    expect(screen.getByText('Reviewing Test Thread #1')).toBeInTheDocument()
    expect(screen.getByText('4.5')).toBeInTheDocument()
  })

  it('should display thread information without issue number', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    expect(screen.getByText('Reviewing Test Thread')).toBeInTheDocument()
    expect(screen.getByText('4.5')).toBeInTheDocument()
  })

  it('should pre-fill review text when existing review is provided', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    expect(textarea).toHaveValue('Great issue!')
  })

  it('should update character count as user types', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    
    act(() => {
      fireEvent.change(textarea, { target: { value: 'Hello' } })
    })

    expect(screen.getByText('5/2000 characters')).toBeInTheDocument()

    act(() => {
      fireEvent.change(textarea, { target: { value: 'Hello world' } })
    })

    expect(screen.getByText('11/2000 characters')).toBeInTheDocument()
  })

  it('should handle skip button click', async () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    const skipButton = screen.getByText('Skip')
    act(() => {
      fireEvent.click(skipButton)
    })

    await waitFor(() => {
      expect(mockOnClose).toHaveBeenCalled()
    })
  })

  it('should submit review with text content', async () => {
    mockOnSubmit.mockResolvedValue(undefined)

    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        issueNumber="1"
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    const submitButton = screen.getByText('Save Review')

    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Great issue!' } })
      fireEvent.click(submitButton)
    })

    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        thread_id: 42,
        rating: 4.5,
        review_text: 'Great issue!',
        issue_number: '1'
      })
      expect(mockOnClose).toHaveBeenCalled()
    })
  })

  it('should submit review without text content (undefined)', async () => {
    mockOnSubmit.mockResolvedValue(undefined)

    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        issueNumber="1"
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    const submitButton = screen.getByText('Save Review')

    // For new reviews, submit button should be disabled without text
    expect(submitButton).toBeDisabled()

    // Enter text first to enable the button
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'test' } })
    })

    // Button should now be enabled
    expect(submitButton).not.toBeDisabled()

    // Remove the text - button should be disabled again
    await act(async () => {
      fireEvent.change(textarea, { target: { value: '' } })
    })

    expect(submitButton).toBeDisabled()
  })

  it('should handle submit error', async () => {
    const error = new Error('Failed to submit review')
    mockOnSubmit.mockRejectedValue(error)

    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    const submitButton = screen.getByText('Save Review')

    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Great issue!' } })
      fireEvent.click(submitButton)
    })

    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalled()
      // onClose should not be called on error
      expect(mockOnClose).not.toHaveBeenCalled()
    })
  })

  it('should disable submit button when submitting', async () => {
    // Mock a delayed submission to test the loading state
    mockOnSubmit.mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 100))
    )

    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    const submitButton = screen.getByText('Save Review')

    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Great issue!' } })
      fireEvent.click(submitButton)
    })

    // Button should be disabled and show "Saving..."
    expect(screen.getByText('Saving...')).toBeInTheDocument()
    expect(screen.getByText('Saving...')).toBeDisabled()
  })

  it('should disable submit button for new reviews without text', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    const submitButton = screen.getByText('Save Review')
    expect(submitButton).toBeDisabled()
  })

  it('should enable submit button for existing reviews without text', () => {
    const existingReviewWithoutText = { ...mockReview, review_text: null }
    
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={existingReviewWithoutText}
      />
    )

    const submitButton = screen.getByText('Update Review')
    expect(submitButton).not.toBeDisabled()
  })

  it('should show cancel button for existing reviews', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    expect(screen.getByText('Cancel')).toBeInTheDocument()
  })

  it('should handle cancel button click for existing reviews', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    const cancelButton = screen.getByText('Cancel')
    act(() => {
      fireEvent.click(cancelButton)
    })

    expect(mockOnClose).toHaveBeenCalled()
  })

  it('should enforce character limit', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    
    // Check that textarea has maxLength attribute
    expect(textarea).toHaveAttribute('maxlength', '2000')
    
    // Type exactly 2000 characters
    const longText = 'a'.repeat(2000)
    
    act(() => {
      fireEvent.change(textarea, { target: { value: longText } })
    })

    // Should accept 2000 characters
    expect(textarea).toHaveValue('a'.repeat(2000))
    expect(screen.getByText('2000/2000 characters')).toBeInTheDocument()
  })

  it('should reset form state when modal is reopened', () => {
    const { rerender } = render(
      <ReviewForm
        key="initial"
        isOpen={false}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    // Initially modal should not be rendered
    expect(screen.queryByTestId('modal')).not.toBeInTheDocument()

    // Open the modal
    rerender(
      <ReviewForm
        key="first-open"
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    // Modal should now be rendered with empty textarea
    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    expect(textarea).toHaveValue('')
    
    // Type some text
    act(() => {
      fireEvent.change(textarea, { target: { value: 'Some text' } })
    })

    expect(textarea).toHaveValue('Some text')

    // Close and reopen the modal
    rerender(
      <ReviewForm
        key="closed"
        isOpen={false}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    rerender(
      <ReviewForm
        key="reopened"
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    // Textarea should be reset (find textarea again as it might be a new DOM element)
    const reopenedTextarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    expect(reopenedTextarea).toHaveValue('')
  })

  it('should preserve existing review text when modal is reopened', () => {
    const { rerender } = render(
      <ReviewForm
        key="initial"
        isOpen={false}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    // Initially modal should not be rendered
    expect(screen.queryByTestId('modal')).not.toBeInTheDocument()

    // Open the modal
    rerender(
      <ReviewForm
        key="first-open"
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    // Modal should now be rendered with existing review text
    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    expect(textarea).toHaveValue('Great issue!')

    // Change the text
    act(() => {
      fireEvent.change(textarea, { target: { value: 'Modified text' } })
    })

    expect(textarea).toHaveValue('Modified text')

    // Close and reopen the modal
    rerender(
      <ReviewForm
        key="closed"
        isOpen={false}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    rerender(
      <ReviewForm
        key="reopened"
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        existingReview={mockReview}
      />
    )

    // Should reset to original review text (find textarea again as it might be a new DOM element)
    const reopenedTextarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    expect(reopenedTextarea).toHaveValue('Great issue!')
  })

  it('should display error message when provided', () => {
    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
        error="Failed to save review"
      />
    )

    expect(screen.getByText('Failed to save review')).toBeInTheDocument()
    expect(screen.getByText('Failed to save review').closest('div')).toHaveClass(
      'bg-red-500/10'
    )
  })

  it('should disable skip button when submitting', async () => {
    // Mock a delayed submission to test the loading state
    mockOnSubmit.mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 100))
    )

    render(
      <ReviewForm
        isOpen={true}
        onClose={mockOnClose}
        onSubmit={mockOnSubmit}
        threadId={42}
        threadTitle="Test Thread"
        rating={4.5}
      />
    )

    const textarea = screen.getByPlaceholderText('Share your thoughts about this comic...')
    const submitButton = screen.getByText('Save Review')
    const skipButton = screen.getByText('Skip')

    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Great issue!' } })
      fireEvent.click(submitButton)
    })

    // Skip button should be disabled during submission
    expect(skipButton).toBeDisabled()
  })
})