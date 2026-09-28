import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import LandingPage from '../pages/LandingPage'
import { markReturningVisitor } from '../utils/returningVisitor'

function renderLanding() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  )
}

describe('LandingPage product voice (issue #2928)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('leads with the roll/queue concept instead of a generic headline', () => {
    renderLanding()
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: /dice-driven reading queue/i,
      }),
    ).toBeInTheDocument()
  })

  it('explains the roll mechanic as a numbered queue-then-roll-then-rate flow', () => {
    renderLanding()
    const howItWorks = screen.getByRole('region', { name: 'How the roll works' })
    expect(within(howItWorks).getByRole('heading', { name: /1\. Build your queue/ })).toBeInTheDocument()
    expect(within(howItWorks).getByRole('heading', { name: /2\. Roll for your next read/ })).toBeInTheDocument()
    expect(within(howItWorks).getByRole('heading', { name: /3\. Read, rate, repeat/ })).toBeInTheDocument()
  })

  it('states the shipped rating range and rating threshold, not a vague benefit', () => {
    renderLanding()
    const howItWorks = screen.getByRole('region', { name: 'How the roll works' })
    expect(howItWorks).toHaveTextContent(/rate it 0\.5[–-]5\.0/i)
    expect(howItWorks).toHaveTextContent(/4\.0 or higher/i)
  })

  it('describes continuity as a pool gate rather than claiming a crossover boost', () => {
    renderLanding()
    const differentiators = screen.getByRole('region', { name: "Why it's not just a tracker" })
    expect(differentiators).toHaveTextContent(/held out of the pool/i)
    expect(differentiators).not.toHaveTextContent(/get a boost/i)
  })

  it('removes the generic SaaS marketing phrases the issue calls out', () => {
    renderLanding()
    const removedPhrases = [
      /smart tracking/i,
      /join the community/i,
      /in 60 seconds/i,
      /no credit card/i,
      /sign up free/i,
      /dice-driven discovery/i,
    ]
    for (const phrase of removedPhrases) {
      expect(screen.queryByText(phrase)).not.toBeInTheDocument()
    }
  })

  it('consolidates open-source positioning into a single source link', () => {
    renderLanding()
    const sourceLinks = screen.getAllByRole('link', { name: /source on github/i })
    expect(sourceLinks).toHaveLength(1)
    expect(sourceLinks[0]).toHaveAttribute('href', 'https://github.com/JoshCLWren/comic-pile')
    expect(sourceLinks[0]).toHaveAttribute('rel', 'noreferrer')
  })

  it('routes a first-time visitor to register and offers the sign-in path', () => {
    renderLanding()
    expect(screen.getByRole('link', { name: /create your queue/i })).toHaveAttribute(
      'href',
      '/register',
    )
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
    expect(screen.getByText(/already have an account\?/i)).toBeInTheDocument()
  })

  it('greets a returning visitor without changing the auth routes', () => {
    markReturningVisitor()
    renderLanding()
    expect(screen.getByText('Welcome back')).toBeInTheDocument()
    expect(screen.queryByText(/already have an account\?/i)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /create your queue/i })).toHaveAttribute(
      'href',
      '/register',
    )
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  })
})
