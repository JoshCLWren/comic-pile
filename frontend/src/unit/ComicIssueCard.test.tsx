import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ComicIssueCard, ComicIssueCover, ComicIssueRatingSlider } from '../components/ComicIssueCard'
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
