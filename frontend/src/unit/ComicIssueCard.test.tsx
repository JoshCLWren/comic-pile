import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ComicIssueAvailability, ComicIssueCard, ComicIssueCover, ComicIssueIdentity, ComicIssueRatingSlider } from '../components/ComicIssueCard'
import { issueCardsApi, type IssueCard, type IssueReadRateResponse } from '../services/issueCardsApi'

const card: IssueCard = {
  issue_id: 75, thread_id: 8, thread_title: 'Cable', issue_number: 'Annual 1', status: 'read',
  rating: 4, mapping_state: 'unmapped', has_confirmed_identity: false,
}
const receipt: IssueReadRateResponse = {
  issue: card, thread: { thread_id: 8, issues_remaining: 1, status: 'active' },
  read_event_created: false, rating_event_created: true, replayed: false,
}
const patch = vi.spyOn(issueCardsApi, 'patchIssue')
function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
function mount(status: 'read' | 'unread' = 'read') {
  const onMutated = vi.fn()
  render(<ComicIssueCard issueId={75} card={{ ...card, status }} threadTitle="Fallback" issueNumber="1" status={status} showMapping={false} onMutated={onMutated} />, { wrapper })
  return onMutated
}
beforeEach(() => { patch.mockReset(); patch.mockResolvedValue(receipt) })

describe('shared direct issue card', () => {
  it('edits a persisted rating without sending a read status or another read', async () => {
    const onMutated = mount()
    expect(screen.getByText(/Rated 4/)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Edit rating' }))
    expect(screen.getByRole('slider')).toHaveValue('4')
    fireEvent.change(screen.getByRole('slider'), { target: { value: '4.5' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save rating' }))
    await waitFor(() => expect(onMutated).toHaveBeenCalledWith(receipt))
    expect(patch).toHaveBeenCalledExactlyOnceWith(75, expect.objectContaining({ rating: 4.5, status: undefined }))
    expect(screen.queryByTestId('comic-issue-rating-editor')).not.toBeInTheDocument()
  })

  it('retries an ambiguous rating failure with the same key and draft', async () => {
    patch.mockRejectedValueOnce(new Error('save offline'))
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'Edit rating' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save rating' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('save offline')
    expect(screen.getByRole('slider')).toHaveValue('4')
    await userEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(patch).toHaveBeenCalledTimes(2)
    expect(patch.mock.calls[1]).toEqual(patch.mock.calls[0])
  })

  it('retries an explicit unread correction without sending a rating', async () => {
    patch.mockRejectedValueOnce(new Error('unread offline'))
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('unread offline')
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(patch).toHaveBeenCalledWith(75, expect.objectContaining({ status: 'unread', rating: undefined }))
    expect(patch.mock.calls[1]).toEqual(patch.mock.calls[0])
  })

  it('opens and cancels a manual read without writing and starts a changed intent with a fresh key', async () => {
    patch.mockRejectedValueOnce(new Error('offline'))
    mount('unread')
    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(patch).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Rate / Mark read' }))
    await userEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    await screen.findByRole('alert')
    fireEvent.change(screen.getByRole('slider'), { target: { value: '5' } })
    await userEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2))
    expect(patch.mock.calls[1]?.[1].idempotencyKey).not.toBe(patch.mock.calls[0]?.[1].idempotencyKey)
    expect(patch.mock.calls[1]?.[1].rating).toBe(5)
  })

  it('keeps external unowned entries free of personal read and correction controls', () => {
    render(<ComicIssueCard issueId={75} threadTitle="Cable" issueNumber="75" status="unread" isOwned={false} showMapping={false} variant="compact" advisory="Add this exact issue to your library." />, { wrapper })
    expect(screen.getByText('Add this exact issue to your library.')).toBeVisible()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('data-variant', 'compact')
  })
})

describe('issue-specific cover and shared rating input', () => {
  it('keeps the provider URL unchanged, replaces broken art, and recovers on mapping change', () => {
    const first = 'https://comicvine.gamespot.com/a/cover.jpg?size=original'
    const second = 'https://comicvine.gamespot.com/b/annual.jpg'
    const { rerender } = render(<ComicIssueCover coverImageUrl={first} threadTitle="Cable" issueNumber="Annual 1" variant="featured" />)
    expect(screen.getByRole('img')).toHaveAttribute('src', first)
    expect(screen.getByRole('img')).toHaveAttribute('loading', 'eager')
    fireEvent.error(screen.getByRole('img'))
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toHaveAttribute('aria-label', 'No cover for Cable #Annual 1')
    rerender(<ComicIssueCover coverImageUrl={second} threadTitle="Cable" issueNumber="Annual 1" variant="compact" />)
    expect(screen.getByRole('img')).toHaveAttribute('src', second)
    expect(screen.getByRole('img')).toHaveAttribute('loading', 'lazy')
    rerender(<ComicIssueCover coverImageUrl="" threadTitle="Cable" issueNumber="Annual 1" />)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('supports host-owned labels and value presentation without duplicate slider descriptions', () => {
    const change = vi.fn()
    const { rerender } = render(<ComicIssueRatingSlider value={3.5} onChange={change} showValue={false} showScaleNote={false} describedBy="host-description" inputId="host-input" />)
    expect(screen.getByRole('slider')).toHaveAttribute('aria-describedby', 'host-description')
    fireEvent.change(screen.getByRole('slider'), { target: { value: '4' } })
    expect(change).toHaveBeenCalledWith('4')
    expect(screen.queryByText('3.5')).not.toBeInTheDocument()
    rerender(<ComicIssueRatingSlider value={5} onChange={change} showValue={false} disabled />)
    expect(screen.getByRole('slider')).not.toHaveAttribute('aria-describedby')
    expect(screen.getByRole('slider')).toBeDisabled()
  })
})

describe('exact issue projection fallback and accessibility boundaries', () => {
  it('keeps an issue manually readable when a bounded card lookup omits its projection', async () => {
    const onMutated = vi.fn()
    render(
      <ComicIssueCard
        issueId={75}
        card={null}
        threadTitle="B.P.R.D."
        issueNumber="Winter Special"
        status="unread"
        showMapping={false}
        onMutated={onMutated}
      />,
      { wrapper },
    )
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('aria-label', 'Issue B.P.R.D. #Winter Special')
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toBeVisible()
    expect(screen.getByText('Unread')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))
    expect(screen.getByRole('slider')).toHaveValue('3.5')
    expect(screen.getByText('Direct read only — no die or queue change.')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        75,
        expect.objectContaining({ status: 'read', rating: 3.5, idempotencyKey: expect.any(String) }),
      ),
    )
    await waitFor(() => expect(onMutated).toHaveBeenCalledWith(receipt))
  })

  it('prefers the canonical projection over a stale row without confusing the issue identity', () => {
    const url = 'https://comicvine.gamespot.com/a/annual-1.jpg?original=1'
    render(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, rating: 4.5, cover_image_url: url }}
        threadTitle="Stale series"
        issueNumber="2"
        status="unread"
        rating={1}
        variant="featured"
        showMapping={false}
      />,
      { wrapper },
    )
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('aria-label', 'Issue Cable #Annual 1')
    expect(screen.getByRole('img')).toHaveAttribute('src', url)
    expect(screen.getByRole('img')).toHaveAttribute('loading', 'eager')
    expect(screen.getByText(/Rated 4.5/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Read now' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit rating' })).toBeEnabled()
  })

  it('preserves owning-row title, number and rating when optional projection fields are empty', async () => {
    render(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, thread_title: '', issue_number: '', rating: null, cover_image_url: null }}
        threadTitle="The Dead Remembered"
        issueNumber="2"
        status="unread"
        rating={2.5}
        showMapping={false}
      />,
      { wrapper },
    )
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('aria-label', 'Issue The Dead Remembered #2')
    expect(screen.getByText(/Rated 2.5/)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Edit rating' }))
    expect(screen.getByRole('slider')).toHaveValue('2.5')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(patch).not.toHaveBeenCalled()
  })

  it('only shows a rating for read issues with a stored value and hides empty advisories', () => {
    const { rerender } = render(
      <>
        <ComicIssueIdentity threadTitle="Cable" issueNumber="Annual 1" status="read" rating={null} variant="featured" />
        <ComicIssueAvailability advisory={null} />
      </>,
    )
    expect(screen.getByText('Read')).toBeVisible()
    expect(screen.queryByText(/Rated /)).not.toBeInTheDocument()
    expect(screen.queryByTestId('comic-issue-availability')).not.toBeInTheDocument()
    rerender(
      <>
        <ComicIssueIdentity threadTitle="Cable" issueNumber="Annual 1" status="unread" rating={4} />
        <ComicIssueAvailability advisory="Normally follows B.P.R.D." />
      </>,
    )
    expect(screen.getByText('Unread')).toBeVisible()
    expect(screen.queryByText(/Rated /)).not.toBeInTheDocument()
    expect(screen.getByTestId('comic-issue-availability')).toHaveTextContent('Normally follows B.P.R.D.')
  })

  it('keeps default slider value descriptions and clamps the painted track at its bounds', () => {
    const onChange = vi.fn()
    const { rerender } = render(<ComicIssueRatingSlider value={0} onChange={onChange} />)
    const slider = screen.getByRole('slider')
    expect(slider).toHaveAttribute('aria-describedby', 'comic-issue-rating-value')
    expect(screen.getByText('0.0')).toHaveAttribute('id', 'comic-issue-rating-value')
    expect(slider.style.getPropertyValue('--slider-fill')).toBe('0%')
    expect(screen.getByText('0.5 – 5.0 in half steps')).toBeVisible()
    rerender(<ComicIssueRatingSlider value={6} onChange={onChange} />)
    expect(slider.style.getPropertyValue('--slider-fill')).toBe('100%')
    expect(screen.getByText('6.0')).toBeVisible()
  })
})
