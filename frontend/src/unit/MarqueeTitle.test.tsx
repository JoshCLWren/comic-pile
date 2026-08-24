import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { MarqueeTitle } from '../components/MarqueeTitle'

it('renders a wrapped multi-line title', () => {
  render(<MarqueeTitle title="A deliberately long comic title that should wrap" className="custom-title" />)

  const heading = screen.getByRole('heading', { name: 'A deliberately long comic title that should wrap' })
  expect(heading).toHaveClass('whitespace-normal', 'break-words', 'custom-title')
  expect(screen.getAllByText('A deliberately long comic title that should wrap')).toHaveLength(1)
})

it('renders a compact title without overflow clipping', () => {
  render(<MarqueeTitle title="Compact title" />)

  const heading = screen.getByRole('heading', { name: 'Compact title' })
  expect(heading).toHaveClass('whitespace-normal', 'break-words')
  expect(screen.getByText('Compact title')).toBeInTheDocument()
})
