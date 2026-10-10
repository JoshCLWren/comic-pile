import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Tag } from '../types'

const { createTagMock, listTagsMock } = vi.hoisted(() => ({
  createTagMock: vi.fn(),
  listTagsMock: vi.fn(),
}))

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: listTagsMock,
    getTag: vi.fn(),
    createTag: createTagMock,
    updateTag: vi.fn(),
    deleteTag: vi.fn(),
    assignTag: vi.fn(),
    unassignTag: vi.fn(),
    getTagUsage: vi.fn(),
    getEffectiveTags: vi.fn(),
    bulkTagOperations: vi.fn(),
  },
}))

import { TagInput } from '../components/tags/TagInput'

const globalTag: Tag = {
  id: 10,
  name: 'Horror',
  normalized_name: 'horror',
  scope: 'global',
  owner_user_id: null,
  color: '#DC2626',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const privateTag: Tag = {
  id: 11,
  name: 'Cosmic',
  normalized_name: 'cosmic',
  scope: 'private',
  owner_user_id: 4,
  color: '#4F46E5',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function renderInput(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  )
}

async function typeQuery(value: string) {
  const input = screen.getByPlaceholderText('Add tags...')
  await userEvent.click(input)
  await userEvent.type(input, value)
}

beforeEach(() => {
  listTagsMock.mockReset().mockResolvedValue([globalTag, privateTag])
  createTagMock.mockReset()
})

describe('TagInput', () => {
  it('renders the picker without opening a menu until the input is focused', () => {
    renderInput(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    expect(screen.getByPlaceholderText('Add tags...')).toBeInTheDocument()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('shows a selected tag with a labelled remove control', async () => {
    const onTagsChange = vi.fn()
    renderInput(<TagInput selectedTags={[globalTag]} onTagsChange={onTagsChange} />)

    expect(screen.getByText('Horror')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove Horror' }))

    expect(onTagsChange).toHaveBeenCalledWith([])
  })

  it('selects an existing visible tag from the menu', async () => {
    const onTagsChange = vi.fn()
    renderInput(<TagInput selectedTags={[]} onTagsChange={onTagsChange} />)

    await typeQuery('hor')
    await userEvent.click(await screen.findByRole('option', { name: /Horror/ }))

    await waitFor(() => {
      expect(onTagsChange).toHaveBeenCalledWith([globalTag])
    })
  })

  it('offers inline private-tag creation when nothing matches', async () => {
    const onTagsChange = vi.fn()
    const brandNewTag: Tag = { ...privateTag, id: 12, name: 'Weird', normalized_name: 'weird' }
    createTagMock.mockResolvedValue({ tag: brandNewTag })

    renderInput(<TagInput selectedTags={[]} onTagsChange={onTagsChange} />)

    await typeQuery('Weird')
    await userEvent.click(await screen.findByRole('option', { name: /Create "Weird"/ }))

    await waitFor(() => {
      expect(createTagMock).toHaveBeenCalledWith({
        name: 'Weird',
        scope: 'private',
        color: 'red',
        include_near_matches: true,
      })
    })
    await waitFor(() => {
      expect(onTagsChange).toHaveBeenCalledWith([brandNewTag])
    })
  })

  it('surfaces a near-global match and explains why creating a duplicate is discouraged', async () => {
    renderInput(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    await typeQuery('Horor')

    // One edit away from "horror", so it is offered as a near match...
    expect(await screen.findByRole('option', { name: /Horror/ })).toBeInTheDocument()
    // ...and the create row is still available because the user may override.
    expect(screen.getByRole('option', { name: /Create "Horor"/ })).toBeInTheDocument()
    expect(
      screen.getByText(/Similar global tags exist/),
    ).toBeInTheDocument()
  })

  it('never offers to create a private duplicate for an exact normalized match', async () => {
    renderInput(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    await typeQuery('HORROR')

    expect(await screen.findByRole('option', { name: /Horror/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Create/ })).not.toBeInTheDocument()
  })

  it('says no existing tags match while still offering inline creation', async () => {
    renderInput(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    await typeQuery('zzzznothing')

    expect(await screen.findByText('No existing tags match')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Create "zzzznothing"/ })).toBeInTheDocument()
  })

  it('does not offer an already-selected tag again', async () => {
    renderInput(<TagInput selectedTags={[globalTag]} onTagsChange={vi.fn()} />)

    await typeQuery('hor')

    expect(await screen.findByText('No existing tags match')).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /^Horror/ })).not.toBeInTheDocument()
  })

  it('offers no options at all when creation is disabled by the caller', async () => {
    renderInput(
      <TagInput selectedTags={[]} onTagsChange={vi.fn()} showCreateOption={false} />,
    )

    await typeQuery('zzzznothing')

    expect(await screen.findByText('No tags found')).toBeInTheDocument()
  })

  it('enforces the maximum number of selectable tags', async () => {
    const onTagsChange = vi.fn()
    renderInput(
      <TagInput selectedTags={[globalTag]} onTagsChange={onTagsChange} maxTags={1} />,
    )

    expect(screen.getByText('Maximum 1 tags allowed')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Add tags...')).toBeDisabled()

    await typeQuery('cos')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onTagsChange).not.toHaveBeenCalled()
  })

  it('disables the picker when the caller disables it', () => {
    renderInput(<TagInput selectedTags={[]} onTagsChange={vi.fn()} disabled />)

    expect(screen.getByPlaceholderText('Add tags...')).toBeDisabled()
  })

  it('closes the menu when the user clicks outside', async () => {
    renderInput(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    await typeQuery('hor')
    expect(await screen.findByRole('listbox')).toBeInTheDocument()

    await userEvent.click(document.body)

    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    })
  })
})