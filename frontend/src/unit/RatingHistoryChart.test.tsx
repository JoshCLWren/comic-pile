import { render, screen, within, act, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { RatingHistoryChart } from '../components/RatingHistoryChart'
import type { CreatorIssueRow } from '../services/api-creators'

function renderChart(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

function stubResizeObserver() {
  const callbacks: ((entries: Array<{ contentRect: { width: number } }>) => void)[] = []
  vi.stubGlobal(
    'ResizeObserver',
    vi.fn(function (
      this: { observe: unknown; disconnect: unknown },
      callback: (entries: Array<{ contentRect: { width: number } }>) => void,
    ) {
      callbacks.push(callback)
      this.observe = vi.fn()
      this.disconnect = vi.fn()
      return this
    }),
  )
  return callbacks
}

afterEach(() => {
  vi.unstubAllGlobals()
})

const makeRow = (overrides: Partial<CreatorIssueRow> = {}): CreatorIssueRow => ({
  issue_id: 1,
  issue_number: '1',
  thread_id: 1,
  thread_title: 'Series',
  status: 'read',
  roles: ['writer'],
  effective_rating: 4,
  rating_timestamp: '2025-01-01T00:00:00Z',
  sort_key: '1',
  ...overrides,
})

describe('RatingHistoryChart', () => {
  it('renders empty state when no rated issues', () => {
    render(<RatingHistoryChart ratedIssues={[]} />)
    expect(screen.getByText(/No rating history available/)).toBeInTheDocument()
  })

  it('renders chart with rated issues', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 3, rating_timestamp: '2025-01-01T00:00:00Z' }),
      makeRow({ issue_id: 2, effective_rating: 4, rating_timestamp: '2025-02-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('2 ratings')).toBeInTheDocument()
    expect(screen.getByText('Individual rating')).toBeInTheDocument()
  })

  it('does not show rolling-average legend below the minimum sample', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 3, rating_timestamp: '2025-01-01T00:00:00Z' }),
      makeRow({ issue_id: 2, effective_rating: 4, rating_timestamp: '2025-02-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.queryByText(/Rolling average/)).not.toBeInTheDocument()
  })

  it('reports the actual rolling-average window size in the legend', () => {
    // 20 observations -> window = min(5, max(3, floor(20 * 0.3))) = 5
    const issues: CreatorIssueRow[] = Array.from({ length: 20 }, (_, i) =>
      makeRow({
        issue_id: i + 1,
        effective_rating: (i % 5) + 1,
        rating_timestamp: `2025-01-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
      }),
    )
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('Rolling average (5 issues)')).toBeInTheDocument()
  })

  it('uses a smaller window when the sample is sparse', () => {
    // 10 observations -> window = min(5, max(3, floor(10 * 0.3))) = 3
    const issues: CreatorIssueRow[] = Array.from({ length: 10 }, (_, i) =>
      makeRow({
        issue_id: i + 1,
        effective_rating: (i % 5) + 1,
        rating_timestamp: `2025-01-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
      }),
    )
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('Rolling average (3 issues)')).toBeInTheDocument()
  })

  it('never shrinks the rolling-average window below the documented minimum', () => {
    // 4 observations would otherwise compute floor(4 * 0.3) = 1, a one-point "trend".
    const issues: CreatorIssueRow[] = Array.from({ length: 4 }, (_, i) =>
      makeRow({
        issue_id: i + 1,
        effective_rating: (i % 5) + 1,
        rating_timestamp: `2025-01-0${i + 1}T00:00:00Z`,
      }),
    )
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('Rolling average (3 issues)')).toBeInTheDocument()
    expect(screen.queryByText(/Rolling average \(1 issue\)/)).not.toBeInTheDocument()
  })

  it('labels a too-small sample instead of forcing a trend direction', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 3, rating_timestamp: '2025-01-01T00:00:00Z' }),
      makeRow({ issue_id: 2, effective_rating: 4, rating_timestamp: '2025-02-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText(/Trend needs at least 3 ratings; this sample \(2\) is too small/)).toBeInTheDocument()
  })

  it('filters out unrated issues', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: null, rating_timestamp: null }),
      makeRow({ issue_id: 2, effective_rating: 5, rating_timestamp: '2025-03-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('1 rating')).toBeInTheDocument()
  })

  it('keeps one observation per issue when an edited rating is listed twice', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 7, effective_rating: 2, rating_timestamp: '2025-01-01T00:00:00Z' }),
      makeRow({ issue_id: 7, effective_rating: 5, rating_timestamp: '2025-06-01T00:00:00Z' }),
      makeRow({ issue_id: 8, effective_rating: 3, rating_timestamp: '2025-03-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.getByText('2 ratings')).toBeInTheDocument()
  })

  it('orders observations chronologically by effective rating timestamp', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({
        issue_id: 1,
        issue_number: '3',
        effective_rating: 5,
        rating_timestamp: '2025-03-01T00:00:00Z',
      }),
      makeRow({
        issue_id: 2,
        issue_number: '1',
        effective_rating: 1,
        rating_timestamp: '2025-01-01T00:00:00Z',
      }),
      makeRow({
        issue_id: 3,
        issue_number: '2',
        effective_rating: 3,
        rating_timestamp: '2025-02-01T00:00:00Z',
      }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    const table = screen.getByRole('table', { name: 'Rating history data' })
    const issueCells = within(table)
      .getAllByRole('row')
      .slice(1)
      .map(row => within(row).getAllByRole('cell')[0].textContent)
    expect(issueCells).toEqual(['1', '2', '3'])
  })

  it('uses a fixed rating domain so axis labels never repeat', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 4, rating_timestamp: '2025-01-01T00:00:00Z' }),
      makeRow({ issue_id: 2, effective_rating: 4.5, rating_timestamp: '2025-02-01T00:00:00Z' }),
    ]
    const { container } = render(<RatingHistoryChart ratedIssues={issues} />)
    const yTickLabels = Array.from(
      container.querySelectorAll('svg text[text-anchor="end"]'),
    ).map(node => node.textContent)
    expect(yTickLabels).toEqual(['1', '2', '3', '4', '5'])
  })

  it('renders valid date labels for a single observation', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 4, rating_timestamp: '2025-01-15T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    expect(screen.getAllByText(/Jan/).length).toBeGreaterThan(0)
  })

  it('discloses a lower bound when fewer ratings are loaded than exist', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 3, rating_timestamp: '2025-01-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} totalRatings={9} />)
    expect(
      screen.getByText(/Showing 1 rating of 9 ratings\. More of this creator's history is still loading\./),
    ).toBeInTheDocument()
  })

  it('does not claim a lower bound once every rating is loaded', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({ issue_id: 1, effective_rating: 3, rating_timestamp: '2025-01-01T00:00:00Z' }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} totalRatings={1} />)
    expect(screen.queryByText(/still loading/)).not.toBeInTheDocument()
  })

  it('exposes each observation to keyboard and screen-reader users', () => {
    const issues: CreatorIssueRow[] = [
      makeRow({
        issue_id: 1,
        issue_number: '4',
        thread_id: 42,
        thread_title: 'Nightfall',
        effective_rating: 4.5,
        rating_timestamp: '2025-01-01T00:00:00Z',
      }),
    ]
    render(<RatingHistoryChart ratedIssues={issues} />)
    expect(
      screen.getByRole('button', { name: /4\.5 stars for Nightfall #4 rated/ }),
    ).toBeInTheDocument()
  })

  it('offers a working drill-down link from a focused observation', async () => {
    const user = userEvent.setup()
    const issues: CreatorIssueRow[] = [
      makeRow({
        issue_id: 1,
        issue_number: '4',
        thread_id: 42,
        thread_title: 'Nightfall',
        effective_rating: 4.5,
        rating_timestamp: '2025-01-01T00:00:00Z',
      }),
    ]
    renderChart(<RatingHistoryChart ratedIssues={issues} />)
    await user.tab()
    const tooltip = await screen.findByRole('tooltip')
    expect(within(tooltip).getByRole('link', { name: 'Nightfall #4' })).toHaveAttribute(
      'href',
      '/thread/42',
    )
  })

  it('keeps the drill-down link reachable when the pointer moves from a point to the tooltip', async () => {
    const user = userEvent.setup()
    const issues: CreatorIssueRow[] = [
      makeRow({
        issue_id: 1,
        issue_number: '4',
        thread_id: 42,
        thread_title: 'Nightfall',
        effective_rating: 4.5,
        rating_timestamp: '2025-01-01T00:00:00Z',
      }),
    ]
    renderChart(<RatingHistoryChart ratedIssues={issues} />)
    await user.hover(screen.getByRole('button', { name: /4\.5 stars for Nightfall #4 rated/ }))
    const tooltip = await screen.findByRole('tooltip')
    const link = within(tooltip).getByRole('link', { name: 'Nightfall #4' })
    await user.hover(link)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/thread/42')
  })

  it('matches the SVG coordinate width to the measured box so phone labels stay legible', () => {
    const callbacks = stubResizeObserver()
    const issues: CreatorIssueRow[] = Array.from({ length: 8 }, (_, i) =>
      makeRow({
        issue_id: i + 1,
        effective_rating: (i % 5) + 1,
        rating_timestamp: `2025-0${Math.floor(i / 3) + 1}-0${(i % 3) + 1}T00:00:00Z`,
      }),
    )
    const { container } = render(<RatingHistoryChart ratedIssues={issues} />)
    const svg = container.querySelector('svg')
    const defaultViewBox = svg?.getAttribute('viewBox') ?? ''
    const defaultTicks = container.querySelectorAll('svg text[text-anchor="middle"]').length

    act(() => {
      callbacks[0]([{ contentRect: { width: 320 } }])
    })

    // 1:1 pixels means a 12px label is still a 12px label at phone width.
    expect(container.querySelector('svg')?.getAttribute('viewBox')).not.toBe(defaultViewBox)
    expect(container.querySelector('svg')?.getAttribute('viewBox')?.startsWith('0 0 320 ')).toBe(true)
    expect(container.querySelectorAll('svg text[text-anchor="middle"]').length).toBeLessThanOrEqual(
      defaultTicks,
    )
  })

  it('dismisses the tooltip once the pointer leaves the chart', async () => {
    const user = userEvent.setup()
    const issues: CreatorIssueRow[] = [
      makeRow({
        issue_id: 1,
        thread_id: 42,
        thread_title: 'Nightfall',
        effective_rating: 4.5,
        rating_timestamp: '2025-01-01T00:00:00Z',
      }),
    ]
    const { container } = renderChart(<RatingHistoryChart ratedIssues={issues} />)
    await user.hover(screen.getByRole('button', { name: /4\.5 stars/ }))
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    await user.unhover(container.querySelector('.relative')!)
    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument())
  })

  it('holds the tooltip while focus is inside the chart and releases it on exit', async () => {
    const user = userEvent.setup()
    const issues: CreatorIssueRow[] = [
      makeRow({
        issue_id: 1,
        thread_id: 42,
        thread_title: 'Nightfall',
        effective_rating: 4.5,
        rating_timestamp: '2025-01-01T00:00:00Z',
      }),
    ]
    renderChart(<RatingHistoryChart ratedIssues={issues} />)
    await user.tab()
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    await user.tab()
    expect(within(screen.getByRole('tooltip')).getByRole('link')).toHaveFocus()
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    await user.tab()
    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument())
  })
})
