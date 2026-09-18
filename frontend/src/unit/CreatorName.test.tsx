import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { CreatorName } from '../pages/RollPage/components/CreatorName'

describe('CreatorName', () => {
  it('links stable creators to the real creator route', () => {
    render(
      <MemoryRouter>
        <CreatorName creator={{ creator_id: 42, name: 'Jane Author', roles: ['writer'] }} />
      </MemoryRouter>,
    )

    const link = screen.getByRole('link', { name: 'View creator Jane Author' })
    expect(link.getAttribute('href')).toBe('/creators/creator%3A42')
    expect(screen.getByText(/writer/)).toBeInTheDocument()
  })

  it('keeps creators without stable ids as plain text', () => {
    render(
      <MemoryRouter>
        <CreatorName creator={{ creator_id: null, name: 'Mystery Hand', roles: ['artist'] }} />
      </MemoryRouter>,
    )

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('Mystery Hand')).toBeInTheDocument()
  })

  it('renders a stable creator without a role suffix when roles are absent', () => {
    render(
      <MemoryRouter>
        <CreatorName creator={{ creator_id: 42, name: 'Nameless Role', roles: [] }} />
      </MemoryRouter>,
    )

    const link = screen.getByRole('link', { name: 'View creator Nameless Role' })
    expect(link.getAttribute('href')).toBe('/creators/creator%3A42')
    expect(screen.queryByText(/·/)).not.toBeInTheDocument()
  })
})
