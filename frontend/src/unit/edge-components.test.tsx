import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MarqueeTitle } from '../components/MarqueeTitle'
import Swipeable from '../components/Swipeable'
import IssueCorrectionDialog from '../components/IssueCorrectionDialog'
import CollectionDialog from '../components/CollectionDialog'
import MigrationDialog from '../components/MigrationDialog'

const issuesApi = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), move: vi.fn(), markRead: vi.fn(), markUnread: vi.fn() }))
vi.mock('../services/api-issues', () => ({ issuesApi }))
vi.mock('../config/featureFlags', () => ({ collectionsEnabled: true }))
const collection = vi.hoisted(() => ({ createCollection: vi.fn().mockResolvedValue(undefined), updateCollection: vi.fn().mockResolvedValue(undefined) }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => collection }))
const showToast = vi.hoisted(() => vi.fn())
vi.mock('../contexts/useToast', () => ({ useToast: () => ({ showToast }) }))
const migration = vi.hoisted(() => ({ migrateThread: vi.fn() }))
vi.mock('../services/api', () => ({ migrationApi: migration }))

describe('edge component behavior', () => {
  it('renders marquee overflow and responds to resize observation', async () => {
    let callback: (() => void) | undefined
    class Observer {
      observe = vi.fn()
      disconnect = vi.fn()
      constructor(cb: () => void) { callback = cb }
    }
    vi.stubGlobal('ResizeObserver', Observer)
    const { container, rerender } = render(<MarqueeTitle title="A title" className="extra" />)
    const wrapper = container.firstElementChild as HTMLDivElement
    const heading = wrapper.querySelector('h3') as HTMLElement
    Object.defineProperty(wrapper, 'clientWidth', { configurable: true, value: 20 })
    Object.defineProperty(heading, 'scrollWidth', { configurable: true, value: 100 })
    act(() => callback?.())
    await waitFor(() => expect(heading).toHaveClass('marquee-runner'))
    rerender(<MarqueeTitle title="Short" />)
    expect(container.querySelector('h3')).toHaveTextContent('Short')
    vi.unstubAllGlobals()
  })

  it('keeps marquee usable when ResizeObserver is unavailable', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    const { container } = render(<MarqueeTitle title="No observer" />)
    expect(container).toHaveTextContent('No observer')
    vi.unstubAllGlobals()
  })

  it('supports horizontal and vertical swipes, reset clicks, and action buttons', async () => {
    const user = userEvent.setup()
    const cardClick = vi.fn(); const action = vi.fn()
    render(<Swipeable onCardClick={cardClick} actions={[{ icon: 'x', label: 'Delete', color: 'red', onClick: action }]}><span>Card</span></Swipeable>)
    const card = screen.getByText('Card').parentElement as HTMLElement
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchMove(card, { touches: [{ clientX: 90, clientY: 130 }] })
    fireEvent.touchEnd(card)
    fireEvent.click(card)
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchMove(card, { touches: [{ clientX: 0, clientY: 100 }] })
    fireEvent.touchEnd(card)
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(action).toHaveBeenCalled()
    fireEvent.click(card)
    expect(cardClick).toHaveBeenCalled()
  })

  it('corrects existing and newly inserted issue numbers', async () => {
    issuesApi.list.mockResolvedValue({ issues: [
      { id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' },
      { id: 2, thread_id: 1, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' },
    ], next_page_token: null })
    issuesApi.create.mockResolvedValue({ issues: [{ id: 3, issue_number: 'Special', status: 'unread' }] })
    const onClose = vi.fn(); const onSuccess = vi.fn(); const user = userEvent.setup()
    render(<IssueCorrectionDialog isOpen threadId={1} currentIssueNumber="2" totalIssues={2} threadTitle="Saga" onClose={onClose} onSuccess={onSuccess} />)
    await waitFor(() => expect(screen.getByLabelText('Increase issue number')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Decrease issue number' }))
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('validates collection forms and submits create/edit operations', async () => {
    const user = userEvent.setup(); const close = vi.fn()
    const { rerender } = render(<CollectionDialog onClose={close} />)
    await user.click(screen.getByRole('button', { name: 'Create' }))
    expect(screen.getByRole('alert')).toHaveTextContent('required')
    await user.type(screen.getByLabelText(/Collection Name/), 'New collection')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(collection.createCollection).toHaveBeenCalled())
    rerender(<CollectionDialog collection={{ id: 1, user_id: 1, name: 'Old', position: 1, is_default: false, created_at: 'now' }} onClose={close} />)
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(collection.updateCollection).toHaveBeenCalled())
  })

  it('reports collection save failures and closes through keyboard or backdrop', async () => {
    const user = userEvent.setup(); const close = vi.fn()
    collection.createCollection.mockRejectedValueOnce(new Error('collection failed'))
    render(<CollectionDialog onClose={close} />)
    await user.type(screen.getByLabelText(/Collection Name/), 'Archive')
    await user.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('collection failed'))
    fireEvent.keyDown(document, { key: 'Escape' })
    fireEvent.click(screen.getByRole('dialog'))
    expect(close).toHaveBeenCalled()
  })

  it('shows migration warnings for near-complete and completed series', async () => {
    const user = userEvent.setup(); migration.migrateThread.mockResolvedValue({ id: 1 })
    const onComplete = vi.fn()
    render(<MigrationDialog thread={{ id: 1, title: 'Saga' }} onComplete={onComplete} onSkip={vi.fn()} onClose={vi.fn()} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '9')
    await user.type(screen.getByLabelText(/Total Issues/), '10')
    expect(screen.getByRole('status')).toHaveTextContent(/Almost done|One issue away/)
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
  })

  it('validates migration input, previews boundaries, and confirms skipping', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    const onClose = vi.fn()
    migration.migrateThread.mockRejectedValueOnce(new Error('migration failed'))
    render(<MigrationDialog thread={{ id: 2, title: 'Other' }} onComplete={vi.fn()} onSkip={onSkip} onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    expect(screen.getByRole('alert')).toHaveTextContent('fill in both')
    await user.type(screen.getByLabelText(/Last Issue Read/), '0')
    await user.type(screen.getByLabelText(/Total Issues/), '5')
    expect(screen.getByText(/all 5 issues will be marked as unread/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('migration failed'))
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(screen.getByRole('button', { name: 'Yes, Skip' }))
    expect(onSkip).toHaveBeenCalled()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('covers completion warnings and migration boundary validation', async () => {
    const user = userEvent.setup()
    migration.migrateThread.mockResolvedValue({ id: 3 })
    const onComplete = vi.fn()
    const { unmount } = render(<MigrationDialog thread={{ id: 3, title: 'Complete' }} onComplete={onComplete} onSkip={vi.fn()} onClose={vi.fn()} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '10')
    await user.type(screen.getByLabelText(/Total Issues/), '10')
    expect(screen.getByRole('status')).toHaveTextContent(/Completing the series/)
    expect(screen.getByText(/All 10 issues will be marked as read/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    unmount()

    const onClose = vi.fn()
    render(<MigrationDialog thread={{ id: 4, title: 'Invalid' }} onComplete={vi.fn()} onSkip={vi.fn()} onClose={onClose} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '-1')
    await user.type(screen.getByLabelText(/Total Issues/), '0')
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/negative|greater than 0/))
    fireEvent.click(screen.getByRole('dialog'))
    expect(onClose).toHaveBeenCalled()
  })
})
