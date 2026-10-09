import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { searchTagsMock, getNearMatchesMock, checkNameAvailabilityMock, createTagMock } =
  vi.hoisted(() => ({
    searchTagsMock: vi.fn(),
    getNearMatchesMock: vi.fn(),
    checkNameAvailabilityMock: vi.fn(),
    createTagMock: vi.fn(),
  }))

vi.mock('../services/api-tags', () => ({
  tagsApi: {
    listTags: vi.fn(),
    getTag: vi.fn(),
    createTag: createTagMock,
    updateTag: vi.fn(),
    deleteTag: vi.fn(),
    assignTag: vi.fn(),
    unassignTag: vi.fn(),
    getTagUsage: vi.fn(),
    getEffectiveTags: vi.fn(),
    searchTags: searchTagsMock,
    getNearMatches: getNearMatchesMock,
    bulkTagOperations: vi.fn(),
    checkNameAvailability: checkNameAvailabilityMock,
  },
}))

import { TagInput } from '../components/tags/TagInput'
import type { Tag } from '../types'

const existingTag: Tag = {
  id: 10,
  name: 'Horror',
  normalized_name: 'horror',
  scope: 'global',
  owner_user_id: null,
  color: '#DC2626',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const searchResult = {
  id: 10,
  name: 'Horror',
  color: '#DC2626',
  scope: 'global',
  is_private: false,
  is_global: true,
}

beforeEach(() => {
  searchTagsMock.mockReset().mockResolvedValue([])
  getNearMatchesMock.mockReset().mockResolvedValue([])
  checkNameAvailabilityMock.mockReset().mockResolvedValue({ available: true })
  createTagMock.mockReset()
})

describe('TagInput', () => {
  it('shows selected tags with remove buttons', async () => {
    const onTagsChange = vi.fn()

    render(<TagInput selectedTags={[existingTag]} onTagsChange={onTagsChange} />)

    expect(screen.getByText('Horror')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '' }))

    expect(onTagsChange).toHaveBeenCalledWith([])
  })

  it('selects an existing tag from search results', async () => {
    const onTagsChange = vi.fn()
    searchTagsMock.mockResolvedValue([searchResult])

    render(<TagInput selectedTags={[]} onTagsChange={onTagsChange} />)

    await userEvent.type(screen.getByPlaceholderText('Add tags...'), 'Hor')

    const option = await screen.findByText('Horror')
    await userEvent.click(option)

    await waitFor(() => {
      expect(onTagsChange).toHaveBeenCalledWith([
        expect.objectContaining({ id: 10, name: 'Horror' }),
      ])
    })
  })

  it('creates a new private tag inline when the name is available', async () => {
    const onTagsChange = vi.fn()
    const createdTag: Tag = {
      id: 99,
      name: 'Cosmic',
      normalized_name: 'cosmic',
      scope: 'private',
      owner_user_id: 1,
      color: '#DC2626',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    createTagMock.mockResolvedValue(createdTag)

    render(<TagInput selectedTags={[]} onTagsChange={onTagsChange} />)

    await userEvent.type(screen.getByPlaceholderText('Add tags...'), 'Cosmic')

    const createOption = await screen.findByText('Create')
    await userEvent.click(createOption)

    await waitFor(() => {
      expect(createTagMock).toHaveBeenCalledWith({
        name: 'Cosmic',
        scope: 'private',
        color: '#DC2626',
      })
    })

    await waitFor(() => {
      expect(onTagsChange).toHaveBeenCalledWith([createdTag])
    })
  })

  it('shows near matches while creating a tag', async () => {
    searchTagsMock.mockResolvedValue([])
    getNearMatchesMock.mockResolvedValue([{ tag: existingTag, distance: 1 }])

    render(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    await userEvent.type(screen.getByPlaceholderText('Add tags...'), 'Horor')

    expect(await screen.findByText('Similar tags exist:')).toBeInTheDocument()
    expect(screen.getByText('Horror')).toBeInTheDocument()
  })

  it('selects a near match instead of creating a duplicate', async () => {
    const onTagsChange = vi.fn()
    getNearMatchesMock.mockResolvedValue([{ tag: existingTag, distance: 0 }])

    render(<TagInput selectedTags={[]} onTagsChange={onTagsChange} />)

    await userEvent.type(screen.getByPlaceholderText('Add tags...'), 'Horor')

    const match = await screen.findByText('Horror')
    await userEvent.click(match)

    await waitFor(() => {
      expect(onTagsChange).toHaveBeenCalledWith([
        expect.objectContaining({ id: 10, name: 'Horror' }),
      ])
    })
    expect(createTagMock).not.toHaveBeenCalled()
  })

  it('hides the create option when the name is unavailable', async () => {
    searchTagsMock.mockResolvedValue([])
    checkNameAvailabilityMock.mockResolvedValue({ available: false })

    render(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    await userEvent.type(screen.getByPlaceholderText('Add tags...'), 'Horor')

    expect(await screen.findByText('A tag with this name already exists')).toBeInTheDocument()
    expect(screen.queryByText('Create')).not.toBeInTheDocument()
  })

  it('shows a no-results message when search returns nothing', async () => {
    searchTagsMock.mockResolvedValue([])
    getNearMatchesMock.mockResolvedValue([])

    render(<TagInput selectedTags={[]} onTagsChange={vi.fn()} />)

    await userEvent.type(screen.getByPlaceholderText('Add tags...'), 'zzzznothing')

    expect(await screen.findByText('No tags found')).toBeInTheDocument()
  })

  it('enforces the maximum number of selectable tags', async () => {
    const onTagsChange = vi.fn()
    searchTagsMock.mockResolvedValue([searchResult])

    render(<TagInput selectedTags={[existingTag]} onTagsChange={onTagsChange} maxTags={1} />)

    expect(screen.getByText('Maximum 1 tags allowed')).toBeInTheDocument()

    await userEvent.type(screen.getByPlaceholderText('Add tags...'), 'Other')

    const option = await screen.findByText('Other')
    await userEvent.click(option)

    expect(onTagsChange).not.toHaveBeenCalled()
  })
})
