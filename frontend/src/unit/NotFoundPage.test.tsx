import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import NotFoundPage from '../pages/NotFoundPage'

function renderNotFound() {
  return render(
    <MemoryRouter>
      <NotFoundPage />
    </MemoryRouter>,
  )
}

describe('NotFoundPage (issue #3242)', () => {
  it('renders an explicit not-found state with a link back to Roll', () => {
    renderNotFound()

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to roll/i })).toHaveAttribute('href', '/')
  })

  it('carries data-app-shell-ready so the bootstrap shell can never stay mounted', () => {
    const { container } = renderNotFound()

    expect(container.querySelector('[data-app-shell-ready]')).not.toBeNull()
    expect(container.firstElementChild).toHaveAttribute('data-app-shell-ready')
    expect(document.querySelector('[data-app-shell-ready]')?.textContent).toContain(
      'Page not found',
    )
  })
})
