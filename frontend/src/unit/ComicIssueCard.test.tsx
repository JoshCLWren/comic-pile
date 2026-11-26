import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ComicIssueAvailability, ComicIssueCard, ComicIssueCover, ComicIssueIdentity, ComicIssueRatingSlider } from '../components/ComicIssueCard'
import { issueCardsApi, type IssueCard, type IssueReadRateResponse } from '../services/issueCardsApi'


vi.mock('../components/ComicIssueMappingAction', () => ({
  default: ({
    issueId, initialIdentity, fetchEnabled, isOwned, compact, onAddToLibrary, onMapped,
  }: {
    issueId: number | null
    initialIdentity?: { thread_title: string; has_unresolved: boolean; comicvine_issue_id: string | null }
    fetchEnabled: boolean
    isOwned: boolean
    compact: boolean
    onAddToLibrary?: () => void
    onMapped: () => void
  }) => (
    <button
      type="button"
      data-testid="mapping-action"
      data-issue={issueId ?? 'none'}
      data-mapping={initialIdentity?.has_unresolved ? 'review' : initialIdentity ? 'known' : 'missing'}
      data-title={initialIdentity?.thread_title ?? 'missing'}
      data-provider={initialIdentity?.comicvine_issue_id ?? 'none'}
      data-fetch={String(fetchEnabled)}
      data-owned={String(isOwned)}
      data-compact={String(compact)}
      onClick={isOwned ? onMapped : onAddToLibrary}
    >
      Map
    </button>
  ),
}))

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

it('omits its own cover when the host already renders the provider art (#5751)', () => {
  render(
    <ComicIssueCard
      issueId={75}
      card={{ ...card, cover_image_url: 'https://comicvine.gamespot.com/cable-annual-1.jpg' }}
      threadTitle="Fallback"
      issueNumber="1"
      status="read"
      showMapping={false}
      showCover={false}
    />,
    { wrapper },
  )
  expect(screen.queryByTestId('comic-issue-cover')).not.toBeInTheDocument()
  expect(screen.getByRole('article', { name: 'Issue Cable #Annual 1' })).toBeVisible()
})

describe('shared direct issue card', () => {
  it('shows a pending save state until the write settles', async () => {
    let resolvePatch!: (value: IssueReadRateResponse) => void
    patch.mockImplementationOnce(
      () => new Promise<IssueReadRateResponse>((resolve) => { resolvePatch = resolve }),
    )
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'Edit rating' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save rating' }))
    expect(await screen.findByRole('button', { name: 'Saving…' })).toBeDisabled()
    resolvePatch(receipt)
    await waitFor(() =>
      expect(screen.queryByTestId('comic-issue-rating-editor')).not.toBeInTheDocument(),
    )
  })

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

  it('keeps unread correction locked while its direct write is pending', async () => {
    let finish: (value: IssueReadRateResponse) => void = () => {}
    patch.mockImplementationOnce(() => new Promise<IssueReadRateResponse>((resolve) => { finish = resolve }))
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
    expect(await screen.findByRole('button', { name: 'Saving…' })).toBeDisabled()
    expect(patch).toHaveBeenCalledExactlyOnceWith(75, expect.objectContaining({ status: 'unread' }))
    finish(receipt)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Mark unread' })).toBeEnabled())
    expect(patch).toHaveBeenCalledTimes(1)
  })

  it('shows explicit fallback recovery copy when a failed correction has no error detail', async () => {
    patch.mockRejectedValueOnce(new Error(''))
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'Mark unread' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save. Your rating was not recorded')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled()
  })

  it('keeps external unowned entries free of personal read and correction controls', () => {
    render(<ComicIssueCard issueId={75} threadTitle="Cable" issueNumber="75" status="unread" isOwned={false} showMapping={false} variant="compact" advisory="Add this exact issue to your library." />, { wrapper })
    expect(screen.getByText('Add this exact issue to your library.')).toBeVisible()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByTestId('comic-issue-card')).toHaveAttribute('data-variant', 'compact')
  })
})

describe('issue-specific cover and shared rating input', () => {
  it('uses the shared cover for Roll geometry without changing the CDN URL or zoom access', () => {
    const image = 'https://comicvine.gamespot.com/a/uploads/original/cover.jpg'
    const onLoad = vi.fn()
    const { rerender } = render(
      <ComicIssueCover
        coverImageUrl={image}
        threadTitle="Hellboy"
        issueNumber="1"
        variant="featured"
        testId="roll-shared-cover"
        placeholderTestId="cover-placeholder"
        frameClassName="h-full w-full"
        frameStyle={{ aspectRatio: 'auto' }}
        imageClassName="h-full w-full object-contain"
        onImageLoad={onLoad}
      >
        <button type="button">View cover larger</button>
      </ComicIssueCover>,
    )
    expect(screen.getByTestId('roll-shared-cover')).toHaveStyle({ aspectRatio: 'auto' })
    expect(screen.getByRole('img', { name: 'Cover for Hellboy #1' })).toHaveAttribute('src', image)
    expect(screen.getByRole('button', { name: 'View cover larger' })).toBeVisible()
    fireEvent.load(screen.getByRole('img'))
    expect(onLoad).toHaveBeenCalledOnce()
    fireEvent.error(screen.getByRole('img'))
    expect(screen.getByTestId('cover-placeholder')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'View cover larger' })).not.toBeInTheDocument()
    rerender(<ComicIssueCover coverImageUrl={null} threadTitle="Hellboy" issueNumber="2" />)
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toHaveAttribute('aria-label', 'No cover for Hellboy #2')
  })

  it('treats the Roll featured cover as decorative while preserving accessible zoom controls', () => {
    const image = 'https://comicvine.gamespot.com/a/uploads/original/hellboy.jpg'
    const { container } = render(
      <ComicIssueCover
        coverImageUrl={image}
        threadTitle="Hellboy"
        issueNumber="3"
        variant="featured"
        altText=""
        testId="roll-decorative-cover"
      >
        <button type="button" aria-label="View cover larger">Zoom</button>
      </ComicIssueCover>,
    )
    expect(screen.getByTestId('roll-decorative-cover')).toBeVisible()
    expect(container.querySelector('img')).toHaveAttribute('alt', '')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View cover larger' })).toBeEnabled()
  })

  it('lets the shared featured identity be a Roll heading without inventing read status', () => {
    render(
      <ComicIssueIdentity
        threadTitle="Hellboy"
        issueNumber="12"
        status="unread"
        rating={null}
        variant="featured"
        heading
        headingTestId="comic-header-title"
        showStatus={false}
      />,
    )
    expect(screen.getByTestId('comic-header-title').tagName).toBe('H2')
    expect(screen.getByRole('heading', { name: 'Hellboy #12' })).toBeVisible()
    expect(screen.queryByText('Unread')).not.toBeInTheDocument()
  })

  it('keeps the provider URL unchanged, replaces broken art, and recovers on mapping change', () => {
    const first = 'https://comicvine.gamespot.com/a/cover.jpg?size=original'
    const second = 'https://comicvine.gamespot.com/b/annual.jpg'
    const onImageLoad = vi.fn<(img: HTMLImageElement) => void>()
    const { rerender } = render(<ComicIssueCover coverImageUrl={first} threadTitle="Cable" issueNumber="Annual 1" variant="featured" />)
    const firstImage = screen.getByRole('img')
    expect(firstImage).toHaveAttribute('src', first)
    expect(firstImage).toHaveAttribute('loading', 'eager')
    fireEvent.error(firstImage)
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toHaveAttribute('aria-label', 'No cover for Cable #Annual 1')

    rerender(<ComicIssueCover coverImageUrl={second} threadTitle="Cable" issueNumber="Annual 1" variant="compact" onImageLoad={onImageLoad} />)
    const secondImage = screen.getByRole('img')
    expect(secondImage).not.toBe(firstImage)
    expect(secondImage).toHaveAttribute('src', second)
    expect(secondImage).toHaveAttribute('loading', 'lazy')
    expect(secondImage).toHaveClass('opacity-0')

    fireEvent.error(firstImage)
    expect(screen.queryByTestId('comic-issue-cover-placeholder')).not.toBeInTheDocument()
    expect(secondImage).toHaveClass('opacity-0')
    fireEvent.load(secondImage)
    expect(secondImage).toHaveClass('opacity-100')
    expect(onImageLoad).toHaveBeenCalledOnce()
    expect(onImageLoad).toHaveBeenCalledWith(secondImage)

    rerender(<ComicIssueCover coverImageUrl={first} threadTitle="Cable" issueNumber="Annual 1" variant="compact" onImageLoad={onImageLoad} />)
    const retriedFirst = screen.getByRole('img')
    expect(retriedFirst).not.toBe(secondImage)
    expect(retriedFirst).toHaveAttribute('src', first)
    expect(retriedFirst).toHaveClass('opacity-0')
    fireEvent.load(retriedFirst)
    expect(retriedFirst).toHaveClass('opacity-100')
    expect(onImageLoad).toHaveBeenCalledTimes(2)
    expect(onImageLoad).toHaveBeenLastCalledWith(retriedFirst)

    rerender(<ComicIssueCover coverImageUrl="" threadTitle="Cable" issueNumber="Annual 1" />)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('retries a failed cover after an intervening source change before loading', () => {
    const first = 'https://comicvine.gamespot.com/a/cover.jpg?size=original'
    const second = 'https://comicvine.gamespot.com/b/annual.jpg'
    const { rerender } = render(<ComicIssueCover coverImageUrl={first} threadTitle="Cable" issueNumber="Annual 1" />)
    const firstImage = screen.getByRole('img')
    fireEvent.error(firstImage)
    expect(screen.getByTestId('comic-issue-cover-placeholder')).toBeInTheDocument()

    rerender(<ComicIssueCover coverImageUrl={second} threadTitle="Cable" issueNumber="Annual 1" />)
    const pendingSecond = screen.getByRole('img')
    expect(pendingSecond).toHaveAttribute('src', second)
    expect(pendingSecond).toHaveClass('opacity-0')

    rerender(<ComicIssueCover coverImageUrl={first} threadTitle="Cable" issueNumber="Annual 1" />)
    const retriedFirst = screen.getByRole('img')
    expect(retriedFirst).not.toBe(firstImage)
    expect(retriedFirst).not.toBe(pendingSecond)
    expect(retriedFirst).toHaveAttribute('src', first)
    expect(retriedFirst).toHaveClass('opacity-0')
    expect(screen.queryByTestId('comic-issue-cover-placeholder')).not.toBeInTheDocument()

    fireEvent.load(retriedFirst)
    expect(retriedFirst).toHaveClass('opacity-100')
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

describe('shared comic mapping integration', () => {
  it('maps the exact issue when batch metadata is present without gating direct corrections', async () => {
    const mapped = vi.fn()
    render(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, mapping_state: 'confirmed', has_confirmed_identity: true, comicvine_issue_id: '987' }}
        threadTitle="Old title"
        issueNumber="1"
        status="read"
        variant="compact"
        onAddToLibrary={mapped}
      />,
      { wrapper },
    )
    const mapping = screen.getByTestId('mapping-action')
    expect(mapping).toHaveAttribute('data-issue', '75')
    expect(mapping).toHaveAttribute('data-title', 'Cable')
    expect(mapping).toHaveAttribute('data-provider', '987')
    expect(mapping).toHaveAttribute('data-mapping', 'known')
    expect(mapping).toHaveAttribute('data-fetch', 'true')
    expect(mapping).toHaveAttribute('data-owned', 'true')
    expect(mapping).toHaveAttribute('data-compact', 'true')
    expect(screen.getByRole('button', { name: 'Edit rating' })).toBeEnabled()
    await userEvent.click(mapping)
    expect(mapped).not.toHaveBeenCalled()
    expect(patch).not.toHaveBeenCalled()
  })

  it('keeps mapping available while a saved rating draft survives a mapping refresh', async () => {
    const view = render(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, mapping_state: 'confirmed', has_confirmed_identity: true, comicvine_issue_id: '987' }}
        threadTitle="Cable"
        issueNumber="Annual 1"
        status="read"
        variant="compact"
      />,
      { wrapper },
    )

    await userEvent.click(screen.getByRole('button', { name: 'Edit rating' }))
    fireEvent.change(screen.getByRole('slider'), { target: { value: '4.5' } })
    expect(screen.getByTestId('mapping-action')).toBeVisible()
    await userEvent.click(screen.getByTestId('mapping-action'))
    expect(patch).not.toHaveBeenCalled()

    view.rerender(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, rating: 2, mapping_state: 'confirmed', has_confirmed_identity: true, comicvine_issue_id: '654' }}
        threadTitle="Cable"
        issueNumber="Annual 1"
        status="read"
        variant="compact"
      />,
    )

    expect(screen.getByTestId('comic-issue-rating-editor')).toBeVisible()
    expect(screen.getByRole('slider')).toHaveValue('4.5')
    expect(screen.getByTestId('mapping-action')).toHaveAttribute('data-provider', '654')
    await userEvent.click(screen.getByRole('button', { name: 'Save rating' }))
    await waitFor(() =>
      expect(patch).toHaveBeenCalledExactlyOnceWith(
        75,
        expect.objectContaining({ rating: 4.5, status: undefined }),
      ),
    )
  })

  it('keeps exact-issue mapping available while an unmapped comic is marked read', async () => {
    render(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, status: 'unread', rating: null, mapping_state: 'unmapped', has_confirmed_identity: false }}
        threadTitle="Cable"
        issueNumber="Annual 1"
        status="unread"
      />,
      { wrapper },
    )

    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))
    fireEvent.change(screen.getByRole('slider'), { target: { value: '5' } })
    expect(screen.getByTestId('mapping-action')).toBeVisible()
    await userEvent.click(screen.getByTestId('mapping-action'))
    expect(patch).not.toHaveBeenCalled()
    expect(screen.getByRole('slider')).toHaveValue('5')

    await userEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
    await waitFor(() =>
      expect(patch).toHaveBeenCalledExactlyOnceWith(
        75,
        expect.objectContaining({ status: 'read', rating: 5 }),
      ),
    )
  })

  it('marks ambiguous candidates for review while keeping direct read active', async () => {
    render(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, status: 'unread', rating: null, thread_title: '', mapping_state: 'candidate', has_confirmed_identity: false }}
        threadTitle="Fallback series"
        issueNumber="2"
        status="unread"
      />,
      { wrapper },
    )
    const mapping = screen.getByTestId('mapping-action')
    expect(mapping).toHaveAttribute('data-title', 'Fallback series')
    expect(mapping).toHaveAttribute('data-mapping', 'review')
    expect(mapping).toHaveAttribute('data-provider', 'none')
    expect(screen.getByRole('button', { name: 'Read now' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Read now' }))
    expect(screen.getByRole('slider')).toHaveValue('3.5')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(patch).not.toHaveBeenCalled()
  })

  it('does not report unmapped or explicit none states as ambiguous provider mappings', () => {
    const { rerender } = render(
      <ComicIssueCard issueId={75} card={card} threadTitle="Cable" issueNumber="Annual 1" status="read" />,
      { wrapper },
    )
    expect(screen.getByTestId('mapping-action')).toHaveAttribute('data-mapping', 'known')
    rerender(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, mapping_state: ' NONE ' }}
        threadTitle="Cable"
        issueNumber="Annual 1"
        status="read"
      />,
    )
    expect(screen.getByTestId('mapping-action')).toHaveAttribute('data-mapping', 'known')
  })

  it('keeps unowned provider cards actionable through Add to ComicPile with no personal writes', async () => {
    const add = vi.fn()
    render(
      <ComicIssueCard
        issueId={75}
        card={null}
        threadTitle="Provider comic"
        issueNumber="1"
        status="unread"
        isOwned={false}
        onAddToLibrary={add}
        variant="standard"
      />,
      { wrapper },
    )
    const mapping = screen.getByTestId('mapping-action')
    expect(mapping).toHaveAttribute('data-issue', 'none')
    expect(mapping).toHaveAttribute('data-mapping', 'missing')
    expect(mapping).toHaveAttribute('data-fetch', 'false')
    expect(mapping).toHaveAttribute('data-owned', 'false')
    await userEvent.click(mapping)
    expect(add).toHaveBeenCalledOnce()
    expect(screen.queryByRole('button', { name: 'Read now' })).not.toBeInTheDocument()
    expect(patch).not.toHaveBeenCalled()
  })
})

describe('dual issue numbering (#4652)', () => {
  it('renders authored, alternate and provider numbers distinctly', () => {
    render(
      <ComicIssueIdentity
        threadTitle="Saga"
        issueNumber="3"
        issueNumberAlias="100"
        providerIssueNumber="101"
        status="unread"
        rating={null}
      />,
    )
    expect(screen.getByTestId('comic-issue-alias-number')).toHaveTextContent('(100)')
    expect(screen.getByTestId('comic-issue-provider-number')).toHaveTextContent('Provider #101')
  })

  it('hides alias and provider numbers that duplicate the authored number or are blank', () => {
    const { rerender } = render(
      <ComicIssueIdentity
        threadTitle="Saga"
        issueNumber="3"
        issueNumberAlias=" 3 "
        providerIssueNumber="3"
        status="unread"
        rating={null}
      />,
    )
    expect(screen.queryByTestId('comic-issue-alias-number')).not.toBeInTheDocument()
    expect(screen.queryByTestId('comic-issue-provider-number')).not.toBeInTheDocument()
    rerender(
      <ComicIssueIdentity
        threadTitle="Saga"
        issueNumber="3"
        issueNumberAlias="   "
        providerIssueNumber="  "
        status="unread"
        rating={null}
      />,
    )
    expect(screen.queryByTestId('comic-issue-alias-number')).not.toBeInTheDocument()
    expect(screen.queryByTestId('comic-issue-provider-number')).not.toBeInTheDocument()
  })

  it('shows the exact provider identity line only for a confirmed mapping', () => {
    render(
      <ComicIssueCard
        issueId={75}
        card={{ ...card, issue_number: '3', issue_number_alias: '100', has_confirmed_identity: true, comicvine_issue_id: '4000-999', provider_issue_number: '100' }}
        threadTitle="Saga"
        issueNumber="3"
        status="read"
      />,
      { wrapper },
    )
    expect(screen.getByTestId('comic-issue-provider-identity')).toHaveTextContent('ComicVine #4000-999 · provider issue #100')
    expect(screen.getByRole('article', { name: 'Issue Cable #3 (100)' })).toBeVisible()
  })

  it('saves a new alias without a rating or status write', async () => {
    render(
      <ComicIssueCard issueId={75} card={{ ...card, issue_number: '3' }} threadTitle="Saga" issueNumber="3" status="read" />,
      { wrapper },
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add alias' }))
    const input = screen.getByLabelText(/Story-arc or overall number/)
    await userEvent.type(input, '100')
    await userEvent.click(screen.getByRole('button', { name: 'Save alias' }))
    await waitFor(() => expect(screen.queryByTestId('comic-issue-alias-editor')).not.toBeInTheDocument())
    expect(patch).toHaveBeenCalledExactlyOnceWith(75, expect.objectContaining({
      issueNumberAlias: '100', issueNumberAliasProvided: true, rating: undefined, status: undefined,
    }))
  })

  it('clears an existing alias with a blank draft', async () => {
    render(
      <ComicIssueCard issueId={75} card={{ ...card, issue_number: '3', issue_number_alias: '100' }} threadTitle="Saga" issueNumber="3" status="read" />,
      { wrapper },
    )
    await userEvent.click(screen.getByRole('button', { name: 'Edit alias' }))
    await userEvent.clear(screen.getByLabelText(/Story-arc or overall number/))
    await userEvent.click(screen.getByRole('button', { name: 'Save alias' }))
    await waitFor(() => expect(patch).toHaveBeenCalledExactlyOnceWith(75, expect.objectContaining({
      issueNumberAlias: null, issueNumberAliasProvided: true,
    })))
  })

  it('cancels an alias edit without writing', async () => {
    render(
      <ComicIssueCard issueId={75} card={{ ...card, issue_number: '3', issue_number_alias: '100' }} threadTitle="Saga" issueNumber="3" status="read" />,
      { wrapper },
    )
    await userEvent.click(screen.getByRole('button', { name: 'Edit alias' }))
    await userEvent.clear(screen.getByLabelText(/Story-arc or overall number/))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByTestId('comic-issue-alias-editor')).not.toBeInTheDocument()
    expect(patch).not.toHaveBeenCalled()
  })

  it('retries a failed alias-only write with the same idempotency key', async () => {
    patch.mockRejectedValueOnce(new Error('alias offline'))
    render(
      <ComicIssueCard issueId={75} card={{ ...card, issue_number: '3' }} threadTitle="Saga" issueNumber="3" status="read" />,
      { wrapper },
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add alias' }))
    await userEvent.type(screen.getByLabelText(/Story-arc or overall number/), '100')
    await userEvent.click(screen.getByRole('button', { name: 'Save alias' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('alias offline')
    await userEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(patch).toHaveBeenCalledTimes(2)
    expect(patch.mock.calls[1]).toEqual(patch.mock.calls[0])
    expect(patch.mock.calls[1]?.[1].issueNumberAlias).toBe('100')
  })
})
