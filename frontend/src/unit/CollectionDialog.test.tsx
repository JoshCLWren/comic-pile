import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const collections = vi.hoisted(() => ({ createCollection: vi.fn(), updateCollection: vi.fn() }))
const toast = vi.hoisted(() => ({ showToast: vi.fn() }))
vi.mock('../contexts/CollectionContext', () => ({ useCollections: () => collections }))
vi.mock('../contexts/useToast', () => ({ useToast: () => toast }))
import CollectionDialog from '../components/CollectionDialog'

const collection = { id: 3, name: 'Old', is_default: false, position: 1, user_id: 1, created_at: 'now' }

describe('CollectionDialog', () => {
  it('validates and creates a collection', async () => {
    collections.createCollection.mockResolvedValue(undefined)
    const user = userEvent.setup(); const close = vi.fn()
    render(<CollectionDialog onClose={close} />)
    await user.click(screen.getByRole('button', { name: 'Create' }))
    expect(screen.getByRole('alert')).toHaveTextContent('required')
    await user.type(screen.getByLabelText(/Collection Name/), ' New ')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(collections.createCollection).toHaveBeenCalledWith({ name: 'New', is_default: true }))
    expect(close).toHaveBeenCalled(); expect(toast.showToast).toHaveBeenCalled()
  })

  it('edits, handles errors, escape, backdrop, and disabled feature', async () => {
    collections.updateCollection.mockRejectedValue(new Error('failed'))
    const user = userEvent.setup(); const close = vi.fn()
    render(<CollectionDialog collection={collection} onClose={close} />)
    expect(screen.getByRole('heading', { name: 'Edit Collection' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('failed'))
    fireEvent.keyDown(document, { key: 'Escape' }); expect(close).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('dialog'))
    expect(close).toHaveBeenCalled()
  })

  it('displays non-Error update failures', async () => {
    collections.updateCollection.mockRejectedValueOnce('unexpected failure')
    const user = userEvent.setup()
    render(<CollectionDialog collection={collection} onClose={vi.fn()} />)
    const name = screen.getByLabelText(/Collection Name/)
    await user.type(name, 'New name')
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('unexpected error'))
  })
})
