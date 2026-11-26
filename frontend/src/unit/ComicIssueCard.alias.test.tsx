import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { ComicIssueCard } from '../components/ComicIssueCard'
import { issueCardsApi, type IssueCard, type IssueReadRateResponse } from '../services/issueCardsApi'

/** Synthetic mixed-numbering fixture: authored story chapter #3, provider #100. */
const card: IssueCard = {
  issue_id: 4652,
  thread_id: 9,
  thread_title: 'Return of the Master',
  issue_number: '3',
  issue_number_alias: '100',
  display_issue_number: '3 (100)',
  status: 'unread',
  rating: null,
  mapping_state: 'confirmed',
  has_confirmed_identity: true,
  comicvine_issue_id: '777100',
  provider_issue_number: '100',
  cover_image_url: 'https://comicvine.gamespot.com/a/uploads/original/4652.jpg',
}

const receipt: IssueReadRateResponse = {
  issue: card,
  thread: { thread_id: 9, issues_remaining: 1, status: 'active' },
  read_event_created: false,
  rating_event_created: false,
  replayed: false,
}

const patch = vi.spyOn(issueCardsApi, 'patchIssue')

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function mount(overrides: Partial<IssueCard> = {}) {
  const onMutated = vi.fn()
  render(
    <ComicIssueCard
      issueId={card.issue_id}
      card={{ ...card, ...overrides }}
      threadTitle="Fallback"
      issueNumber="fallback"
      status="unread"
      showMapping={false}
      onMutated={onMutated}
    />,
    { wrapper },
  )
  return onMutated
}

beforeEach(() => {
  patch.mockReset()
  patch.mockResolvedValue(receipt)
})

it('renders authored, alternate, provider issue, exact identity and cover distinctly (#4652)', () => {
  mount()
  // One physical comic: the authored story label and its alternate overall number
  // stay separate, and neither is replaced by the provider's number.
  expect(screen.getByRole('article', { name: 'Issue Return of the Master #3 (alt #100)' })).toBeVisible()
  expect(screen.getByTitle('Alternate number: 100')).toHaveTextContent('(alt #100)')
  expect(screen.getByTestId('comic-issue-provider-identity')).toHaveTextContent(
    'ComicVine #777100 · provider issue #100',
  )
  expect(screen.getByRole('img')).toHaveAttribute('src', card.cover_image_url ?? '')
})

it('cancels an alias edit without writing or changing the authored label', async () => {
  mount()
  await userEvent.click(screen.getByTestId('comic-issue-edit-alias'))
  const input = screen.getByLabelText(/Story-arc or overall number/)
  expect(input).toHaveValue('100')
  await userEvent.clear(input)
  await userEvent.type(input, '101')
  await userEvent.click(within(screen.getByTestId('comic-issue-alias-editor')).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByTestId('comic-issue-alias-editor')).not.toBeInTheDocument()
  expect(patch).not.toHaveBeenCalled()
  expect(screen.getByRole('article')).toHaveAttribute('aria-label', 'Issue Return of the Master #3 (alt #100)')
})

it('saves an alias without renumbering the authored issue and clears it with null', async () => {
  const onMutated = mount()
  await userEvent.click(screen.getByTestId('comic-issue-edit-alias'))
  await userEvent.clear(screen.getByLabelText(/Story-arc or overall number/))
  await userEvent.type(screen.getByLabelText(/Story-arc or overall number/), '101')
  await userEvent.click(screen.getByRole('button', { name: 'Save alias' }))
  await waitFor(() => expect(onMutated).toHaveBeenCalledWith(receipt))
  expect(patch).toHaveBeenCalledExactlyOnceWith(4652, {
    status: undefined,
    rating: undefined,
    issueNumberAlias: '101',
    issueNumberAliasProvided: true,
    idempotencyKey: expect.any(String),
  })
  expect(screen.getByRole('article')).toHaveAttribute('aria-label', 'Issue Return of the Master #3 (alt #100)')

  await userEvent.click(screen.getByTestId('comic-issue-edit-alias'))
  await userEvent.clear(screen.getByLabelText(/Story-arc or overall number/))
  fireEvent.change(screen.getByLabelText(/Story-arc or overall number/), { target: { value: '' } })
  await userEvent.click(screen.getByRole('button', { name: 'Save alias' }))
  await waitFor(() => expect(patch).toHaveBeenCalledTimes(2))
  expect(patch.mock.calls[1]?.[1]).toEqual({ ...patch.mock.calls[0]?.[1], issueNumberAlias: null, idempotencyKey: patch.mock.calls[1]?.[1].idempotencyKey })
  expect(patch.mock.calls[1]?.[1].idempotencyKey).not.toBe(patch.mock.calls[0]?.[1].idempotencyKey)
})

it('replays the same stale-version alias intent on retry instead of writing twice', async () => {
  patch.mockRejectedValueOnce(new Error('Version conflict'))
  mount()
  await userEvent.click(screen.getByTestId('comic-issue-edit-alias'))
  await userEvent.clear(screen.getByLabelText(/Story-arc or overall number/))
  await userEvent.type(screen.getByLabelText(/Story-arc or overall number/), '102')
  await userEvent.click(screen.getByRole('button', { name: 'Save alias' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Version conflict')
  await userEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Retry' }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(patch).toHaveBeenCalledTimes(2)
  expect(patch.mock.calls[1]).toEqual(patch.mock.calls[0])
  expect(patch.mock.calls[0]?.[1].issueNumberAlias).toBe('102')
})

it('keeps aliases and direct reading usable while provider identity is conflicted', async () => {
  const onMutated = mount({ has_confirmed_identity: false, mapping_state: 'conflict' })
  expect(screen.queryByTestId('comic-issue-provider-identity')).not.toBeInTheDocument()
  expect(screen.getByRole('article')).toHaveAttribute('aria-label', 'Issue Return of the Master #3 (alt #100)')
  await userEvent.click(screen.getByRole('button', { name: 'Read now' }))
  await userEvent.click(screen.getByRole('button', { name: 'Mark read & save' }))
  await waitFor(() => expect(onMutated).toHaveBeenCalledWith(receipt))
  expect(patch).toHaveBeenCalledExactlyOnceWith(4652, expect.objectContaining({ status: 'read' }))
})

it('does not show an alias that only differs by case or whitespace', () => {
  mount({ issue_number_alias: ' 3 ' })
  expect(screen.getByRole('article')).toHaveAttribute('aria-label', 'Issue Return of the Master #3')
  expect(screen.queryByTitle('Alternate number: 3')).not.toBeInTheDocument()
})
