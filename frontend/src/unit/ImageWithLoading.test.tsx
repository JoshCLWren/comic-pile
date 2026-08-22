import { describe, expect, it, vi } from 'vitest'
import { render, waitFor, act } from '@testing-library/react'
import ImageWithLoading from '../components/ImageWithLoading'

describe('ImageWithLoading', () => {
  it('shows loading spinner initially', () => {
    const { getByRole, queryByText } = render(
      <ImageWithLoading src="https://example.com/image.jpg" />
    )

    // Should show loading spinner (role="status")
    expect(getByRole('status')).toBeInTheDocument()

    // Placeholder shows only a bare spinner, no text message
    expect(queryByText('Loading...')).not.toBeInTheDocument()

    // Should not show the actual image yet (should be transparent)
    const img = document.querySelector('img')
    expect(img).toHaveClass('opacity-0')
  })

  it('centers the spinner inside the sized placeholder box', () => {
    const { getByRole } = render(
      <ImageWithLoading
        src="https://example.com/image.jpg"
        className="w-10 h-14 shrink-0"
      />
    )

    const status = getByRole('status')
    const placeholder = status.closest('div.w-10')
    expect(placeholder).not.toBeNull()
    expect(placeholder).toHaveClass('flex', 'items-center', 'justify-center')

    // Placeholder contains only the spinner subtree, no stray skeleton rectangles
    expect(placeholder?.children).toHaveLength(1)
  })

  it('shows image when loaded', async () => {
    const { getByRole, queryByRole, findByAltText } = render(
      <ImageWithLoading src="https://example.com/image.jpg" alt="Test image" />
    )

    // Should show loading spinner initially
    expect(getByRole('status')).toBeInTheDocument()

    // Find the image element and simulate load
    act(() => {
      const img = document.querySelector('img')
      if (!img) {
        throw new Error('Image element not found')
      }
      img.dispatchEvent(new Event('load'))
    })

    // Should no longer show loading spinner
    expect(await waitFor(() => queryByRole('status'))).not.toBeInTheDocument()
    
    // Should show the image with correct alt text and be opaque
    const img = await findByAltText('Test image')
    expect(img).toHaveClass('opacity-100')
    expect(img).not.toHaveClass('opacity-0')
    expect(img).not.toHaveClass('hidden')
  })

  it('handles image error', async () => {
    const onErrorMock = vi.fn()
    const { getByRole } = render(
      <ImageWithLoading src="https://example.com/image.jpg" onError={onErrorMock} />
    )

    // Should show loading spinner initially
    expect(getByRole('status')).toBeInTheDocument()

    // Find the image element and simulate error
    act(() => {
      const img = document.querySelector('img')
      if (!img) {
        throw new Error('Image element not found')
      }
      img.dispatchEvent(new Event('error'))
    })

    // Should have called the onError callback
    expect(onErrorMock).toHaveBeenCalledTimes(1)
  })
})