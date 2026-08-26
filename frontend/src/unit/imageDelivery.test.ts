import { describe, it, expect } from 'vitest'
import { optimizedImageUrl, optimizedImageSrcSet, IMAGE_WIDTH_VARIANTS } from '../services/imageDelivery'

describe('imageDelivery', () => {
  describe('optimizedImageUrl', () => {
    it('returns null for null or undefined source', () => {
      expect(optimizedImageUrl(null, 240)).toBeNull()
      expect(optimizedImageUrl(undefined, 240)).toBeNull()
    })

    it('passes through data URLs unchanged', () => {
      const dataUrl = 'data:image/png;base64,abc123'
      expect(optimizedImageUrl(dataUrl, 240)).toBe(dataUrl)
    })

    it('passes through blob URLs unchanged', () => {
      const blobUrl = 'blob:https://example.com/abc123'
      expect(optimizedImageUrl(blobUrl, 240)).toBe(blobUrl)
    })

    it('rewrites allowlisted https URLs to the optimizer endpoint', () => {
      const source = 'https://comicvine.gamespot.com/a/uploads/scale_large/0/1/100-1.jpg'
      const result = optimizedImageUrl(source, 240)
      expect(result).toBe('/api/v1/images/optimize?url=https%3A%2F%2Fcomicvine.gamespot.com%2Fa%2Fuploads%2Fscale_large%2F0%2F1%2F100-1.jpg&width=240')
    })

    it('rewrites allowlisted http URLs to the optimizer endpoint', () => {
      const source = 'http://comicvine.gamespot.com/a/uploads/scale_large/0/1/100-1.jpg'
      const result = optimizedImageUrl(source, 240)
      expect(result).toBe('/api/v1/images/optimize?url=http%3A%2F%2Fcomicvine.gamespot.com%2Fa%2Fuploads%2Fscale_large%2F0%2F1%2F100-1.jpg&width=240')
    })

    it('passes through relative URLs unchanged (catch branch)', () => {
      const relativeUrl = '/images/local-cover.jpg'
      expect(optimizedImageUrl(relativeUrl, 240)).toBe(relativeUrl)
    })

    it('passes through unparseable URLs unchanged (catch branch)', () => {
      const unparseable = 'not-a-url-at-all'
      expect(optimizedImageUrl(unparseable, 240)).toBe(unparseable)
    })

    it('passes through non-http(s) protocols unchanged', () => {
      const ftpUrl = 'ftp://example.com/image.jpg'
      expect(optimizedImageUrl(ftpUrl, 240)).toBe(ftpUrl)
    })

    it('uses the provided width parameter', () => {
      const source = 'https://comicvine.gamespot.com/cover.jpg'
      expect(optimizedImageUrl(source, 96)).toContain('width=96')
      expect(optimizedImageUrl(source, 480)).toContain('width=480')
      expect(optimizedImageUrl(source, 720)).toContain('width=720')
    })

    it('accepts numeric widths not in the variant list', () => {
      const source = 'https://comicvine.gamespot.com/cover.jpg'
      const result = optimizedImageUrl(source, 300)
      expect(result).toContain('width=300')
    })
  })

  describe('optimizedImageSrcSet', () => {
    it('returns null for null or undefined source', () => {
      expect(optimizedImageSrcSet(null)).toBeNull()
      expect(optimizedImageSrcSet(undefined)).toBeNull()
    })

    it('builds srcset with default width variants for https URL', () => {
      const source = 'https://comicvine.gamespot.com/cover.jpg'
      const result = optimizedImageSrcSet(source)
      expect(result).toContain('width=96')
      expect(result).toContain('width=240')
      expect(result).toContain('width=480')
      expect(result).toContain('width=720')
      expect(result).toContain('96w')
      expect(result).toContain('720w')
    })

    it('builds srcset with custom width variants', () => {
      const source = 'https://comicvine.gamespot.com/cover.jpg'
      const result = optimizedImageSrcSet(source, [240, 480])
      expect(result).toContain('width=240')
      expect(result).toContain('width=480')
      expect(result).not.toContain('width=96')
      expect(result).not.toContain('width=720')
    })

    it('builds srcset with original URLs for data URLs (passed through)', () => {
      const dataUrl = 'data:image/png;base64,abc123'
      const result = optimizedImageSrcSet(dataUrl)
      expect(result).toContain('data:image/png;base64,abc123')
      expect(result).toContain('96w')
      expect(result).toContain('720w')
    })

    it('builds srcset with original URLs for blob URLs (passed through)', () => {
      const blobUrl = 'blob:https://example.com/abc123'
      const result = optimizedImageSrcSet(blobUrl)
      expect(result).toContain('blob:https://example.com/abc123')
      expect(result).toContain('96w')
      expect(result).toContain('720w')
    })

    it('builds srcset with original URLs for relative URLs (passed through)', () => {
      const relativeUrl = '/images/local-cover.jpg'
      const result = optimizedImageSrcSet(relativeUrl)
      expect(result).toContain('/images/local-cover.jpg')
      expect(result).toContain('96w')
      expect(result).toContain('720w')
    })

    it('filters out null entries from width mapping', () => {
      const source = 'https://comicvine.gamespot.com/cover.jpg'
      // Mix of valid and invalid (data) widths - but all widths produce valid URLs for http(s)
      const result = optimizedImageSrcSet(source, [96, 240])
      const entries = result?.split(', ') ?? []
      expect(entries.length).toBe(2)
    })
  })

  describe('IMAGE_WIDTH_VARIANTS', () => {
    it('exports the expected variant widths', () => {
      expect(IMAGE_WIDTH_VARIANTS).toEqual([96, 240, 480, 720])
    })
  })
})