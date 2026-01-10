import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Navigation from '../components/Navigation'

test('renders navigation links', () => {
  render(
    <MemoryRouter>
      <Navigation />
    </MemoryRouter>
  )

  expect(screen.getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /rate page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /analytics page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /settings page/i })).toBeInTheDocument()
})
