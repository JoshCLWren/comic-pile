import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import GlossaryLink from '../components/GlossaryLink'

describe('GlossaryLink', () => {
  it('renders an in-app link to the canonical glossary definition', () => {
    render(
      <MemoryRouter>
        <GlossaryLink id="crossover">Crossover</GlossaryLink>
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: 'Crossover' })
    expect(link).toHaveAttribute('href', '/glossary#crossover')
  })

  it('points every surface term at its own anchor', () => {
    const terms: Array<[string, string]> = [
      ['continuity-plan', 'Continuity Plan'],
      ['lane', 'Lane'],
      ['reading-order', 'Reading Order'],
      ['projection', 'Projection'],
      ['die-ladder', 'Die ladder'],
      ['autoladder', 'AutoLadder'],
      ['dependency', 'Dependency rule'],
      ['readiness', 'Readiness'],
    ]
    render(
      <MemoryRouter>
        {terms.map(([id, label]) => (
          <GlossaryLink key={id} id={id}>
            {label}
          </GlossaryLink>
        ))}
      </MemoryRouter>,
    )
    for (const [id, label] of terms) {
      expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', `/glossary#${id}`)
    }
  })
})