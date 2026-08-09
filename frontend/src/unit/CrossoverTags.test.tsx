import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { CrossoverTags } from '../components/CrossoverTags'

describe('CrossoverTags', () => {
  it('renders nothing when there are no crossover memberships', () => {
    const { container } = render(
      <MemoryRouter>
        <CrossoverTags groups={[]} />
      </MemoryRouter>,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('renders every crossover as a tappable management link', () => {
    render(
      <MemoryRouter>
        <CrossoverTags
          groups={[
            { id: 7, name: 'Annihilation' },
            { id: 12, name: 'War of Kings' },
          ]}
          label="Crossovers for Nova"
        />
      </MemoryRouter>,
    )

    expect(screen.getByRole('region', { name: 'Crossovers for Nova' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Annihilation' })).toHaveAttribute(
      'href',
      '/crossovers?group=7',
    )
    expect(screen.getByRole('link', { name: 'War of Kings' })).toHaveAttribute(
      'href',
      '/crossovers?group=12',
    )
  })

  it('keeps long crossover names bounded for mobile layouts', () => {
    render(
      <MemoryRouter>
        <CrossoverTags groups={[{ id: 3, name: 'A Very Long Cosmic Crossover Name' }]} />
      </MemoryRouter>,
    )

    const link = screen.getByRole('link', { name: 'A Very Long Cosmic Crossover Name' })
    expect(link).toHaveClass('max-w-full', 'break-words')
    expect(link).not.toHaveClass('truncate')
    expect(link).toHaveAttribute('title', 'A Very Long Cosmic Crossover Name')
  })
})
