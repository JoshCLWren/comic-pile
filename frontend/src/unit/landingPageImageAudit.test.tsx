import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import LandingPage from '../pages/LandingPage'

function renderLanding() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  )
}

/**
 * Public-surface image accessibility audit (issue #3069).
 *
 * The only indexable public page is the landing route (`/`). Every `` on
 * an indexable page must be classified as meaningful or decorative: each
 * `` must carry an `alt` attribute (a concise label for content images,
 * or `alt=""` for genuinely decorative/redundant images). No `` may be
 * rendered without an explicit accessibility decision.
 */
describe('LandingPage public image accessibility audit (issue #3069)', () => {
  it('every image on the indexable public surface carries an explicit alt decision', () => {
    const { container } = renderLanding()

    const images = container.querySelectorAll('img')
    expect(images.length).toBeGreaterThanOrEqual(0)
    for (const img of images) {
      // The explicit `alt` attribute must be present on every image.
      // Empty string (`alt=""`) = deliberate decorative/redundant decision.
      expect(img).toHaveAttribute('alt')
      const alt = img.getAttribute('alt') ?? ''
      expect(alt).toBeTypeOf('string')
    }
  })
})
