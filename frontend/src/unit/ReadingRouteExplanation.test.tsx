import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReadingOrder } from '../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../types'
import { ReadingRouteExplanation } from '../pages/RollPage/components/ReadingRouteExplanation'

const routes = [
  { id: 2, name: 'Secret Wars', completed_items: 2, total_items: 8 },
  { id: 1, name: 'Avengers path', completed_items: 5, total_items: 10 },
] as ReadingOrder[]
const connections = [
  { thread_id: 9, dependency_id: 4, title: 'Prelude', connection_type: 'blocked_by' as const },
] as ConnectedThreadInfo[]

describe('ReadingRouteExplanation', () => {
  it('shows factual route context without a second readiness verdict', () => {
    render(
      <ReadingRouteExplanation
        isOpen
        issueId={7}
        issueLabel="Avengers #7"
        readingOrders={routes}
        connectedThreads={connections}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByRole('dialog', { name: 'Avengers #7' })).toBeVisible()
    expect(screen.getByText('Prelude')).toBeVisible()
    expect(screen.getByText('Avengers path')).toBeVisible()
    expect(screen.getByText('Secret Wars')).toBeVisible()
    expect(screen.getByText(/Roll already selected this issue/i)).toBeVisible()
    expect(screen.queryByText(/readiness/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/eligibility/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })
})
