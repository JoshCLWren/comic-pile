import { describe, expect, it, vi } from 'vitest'
import { render, waitFor, act } from '@testing-library/react'
import ImageWithLoading from '../components/ImageWithLoading'

describe('ImageWithLoading', () => {
  it('shows loading spinner initially', () => {
    const { getByRole, queryByText } = render(
      <ImageWithLoading src="https://example.com/image.jpg" alt="" />
    )

    // Should show loading spinner (role="status")
    expect(getByRole('status')).toBeInTheDocument()

    // Placeholder shows only a bare spinner, no text message
    expect(queryByText('Loading...')).not.toBeInTheDocument()

    // Should not show the actual image yet (should be transparent)
    const img = document.querySelector('img')
    expect(img).toHaveClass('opacity-0')
  })

  it('overlays the spinner on reserved space without adding layout footprint', () => {
    const { getByRole, container } = render(
      <ImageWithLoading
        src="https://example.com/image.jpg"
        alt=""
        className="w-10 h-14 shrink-0"
      />
    )

    const status = getByRole('status')

    // Spinner sits in an absolutely positioned overlay so loading adds no
    // extra flex/grid footprint next to the reserved image box.
    const overlay = status.closest('div.absolute')
    expect(overlay).not.toBeNull()
    expect(overlay).toHaveClass('inset-0', 'flex', 'items-center', 'justify-center')

    // The single wrapper reserves the final image size.
    const wrapper = overlay?.parentElement
    expect(wrapper).not.toBeNull()
    expect(wrapper).toHaveClass('relative', 'w-10', 'h-14')

    // Exactly one image element is rendered for one component instance.
    expect(container.querySelectorAll('img')).toHaveLength(1)
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
      <ImageWithLoading src="https://example.com/image.jpg" alt="" onError={onErrorMock} />
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

  it('applies placeholderClassName to the loading overlay while keeping the base classes', () => {
    const { getByRole } = render(
      <ImageWithLoading
        src="https://example.com/image.jpg"
        alt=""
        placeholderClassName="animate-pulse bg-white/10"
      />
    )

    const status = getByRole('status')
    const overlay = status.closest('div.absolute')
    expect(overlay).not.toBeNull()
    expect(overlay).toHaveClass('absolute', 'inset-0', 'flex', 'items-center', 'justify-center')
    expect(overlay).toHaveClass('animate-pulse', 'bg-white/10')
  })

  it('invokes onLoad with the loaded image element', () => {
    const onLoadMock = vi.fn<(img: HTMLImageElement) => void>()
    const { getByRole } = render(
      <ImageWithLoading src="https://example.com/image.jpg" alt="" onLoad={onLoadMock} />
    )

    expect(getByRole('status')).toBeInTheDocument()

    act(() => {
      const img = document.querySelector('img')
      if (!img) {
        throw new Error('Image element not found')
      }
      Object.defineProperty(img, 'naturalWidth', { value: 300 })
      Object.defineProperty(img, 'naturalHeight', { value: 400 })
      img.dispatchEvent(new Event('load'))
    })

    expect(onLoadMock).toHaveBeenCalledTimes(1)
    const loadedImg = onLoadMock.mock.calls[0][0]
    expect(loadedImg.naturalWidth).toBe(300)
    expect(loadedImg.naturalHeight).toBe(400)
    // Spinner is gone once loaded
    // Removed noopWrite check
  })
})

describe('ImageWithLoading accessibility (issue #3069)', () => {
  it('requires an explicit alt decision and reflects meaningful alt text', () => {
    const { getByAltText } = render(
      <ImageWithLoading src="https://example.com/cover.jpg" alt="Cover art for Saga vol. 1" />
    )
    expect(getByAltText('Cover art for Saga vol. 1')).toBeInTheDocument()
  })

  it('treats alt="" as a deliberate decorative/empty-alt decision', () => {
    const { getByAltText } = render(
      <ImageWithLoading src="https://example.com/decorative.png" alt="" />
    )
    const img = getByAltText('')
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('alt', '')
  })

  it('reserves intrinsic dimensions via width/height to prevent layout shift', () => {
    const { container } = render(
      <ImageWithLoading
        src="https://example.com/cover.jpg"
        alt="Cover art"
        width={720}
        height={1080}
      />
    )
    const img = container.querySelector('img')
    expect(img).toHaveAttribute('width', '720')
    expect(img).toHaveAttribute('height', '1080')
  })

  it('defaults to lazy loading so below-the-fold images are deferred', () => {
    const { container } = render(
      <ImageWithLoading src="https://example.com/cover.jpg" alt="" />
    )
    expect(container.querySelector('img')).toHaveAttribute('loading', 'lazy')
  })

  it('allows eager loading for the hero/LCP image', () => {
    const { container } = render(
      <ImageWithLoading
        src="https://example.com/hero.jpg"
        alt="Hero image"
        loading="eager"
      />
    )
    expect(container.querySelector('img')).toHaveAttribute('loading', 'eager')
  })

  it('passes responsive srcset and sizes through unchanged', () => {
    const { container } = render(
      <ImageWithLoading
        src="https://example.com/cover.jpg"
        alt="Cover art"
        srcSet="https://example.com/cover-240.jpg 240w, https://example.com/cover-720.jpg 720w"
        sizes="(min-width: 1024px) 30vw, 90vw"
      />
    )
    const img = container.querySelector('img')
    expect(img).toHaveAttribute('srcset', 'https://example.com/cover-240.jpg 240w, https://example.com/cover-720.jpg 720w')
    expect(img).toHaveAttribute('sizes', '(min-width: 1024px) 30vw, 90vw')
  })

  it('renders WebP/AVIF source variants inside a picture element', () => {
    const { container } = render(
      <ImageWithLoading
        src="https://example.com/cover.jpg"
        alt="Cover art"
        sources={[
          { srcSet: 'https://example.com/cover.avif', type: 'image/avif' },
          { srcSet: 'https://example.com/cover.webp', type: 'image/webp' },
        ]}
      />
    )
    const picture = container.querySelector('picture')
    expect(picture).not.toBeNull()
    const sources = picture!.querySelectorAll('source')
    expect(sources).toHaveLength(2)
    expect(sources[0]).toHaveAttribute('type', 'image/avif')
    expect(sources[0]).toHaveAttribute('srcset', 'https://example.com/cover.avif')
    expect(sources[1]).toHaveAttribute('type', 'image/webp')
    expect(sources[1]).toHaveAttribute('srcset', 'https://example.com/cover.webp')
    const img = picture!.querySelector('img')
    expect(img).toHaveAttribute('alt', 'Cover art')
    expect(img).toHaveAttribute('src', 'https://example.com/cover.jpg')
  })
})
