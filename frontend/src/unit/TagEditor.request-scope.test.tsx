/**
 * Request-scope regression for the inline tag editor (#4501).
 *
 * The editor is mounted closed on detail surfaces so its open/close animation
 * and focus state stay local. It must not spend a request on the usable-tag
 * catalog until the reader actually opens it: the closed page visible tag
 * chips already come from a separate effective-tags read.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TagSection } from '../components/Tags/TagSection'
import { tagsApi } from '../services/api-tags'

vi.mock('../services/api-tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-tags')>()
  return {
    ...actual,
    tagsApi: {
      ...actual.tagsApi,
      list: vi.fn(),
      effectiveForThread: vi.fn(),
    },
  }
})

const mockedTagsApi = vi.mocked(tagsApi)

beforeEach(() => {
  vi.clearAllMocks()
  mockedTagsApi.list.mockResolvedValue({ tags: [] })
  // SAFETY: the stub supplies the effective-tag fields the chips read.
  mockedTagsApi.effectiveForThread.mockResolvedValue({
    target_type: 'Thread',
    target_id: 42,
    direct_tags: [],
    effective_tags: [],
  } as never)
})

describe('TagEditor request scope', () => {
  it('does not request the usable-tag catalog while the editor is closed', async () => {
    render(
      <TagSection targetType="Thread" targetId={42} targetLabel="Saga" />,
    )

    // The always-visible chips still read effective tags.
    await waitFor(() =>
      expect(mockedTagsApi.effectiveForThread).toHaveBeenCalledWith(42),
    )
    expect(mockedTagsApi.list).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Edit tags' }))

    await waitFor(() => expect(mockedTagsApi.list).toHaveBeenCalled())
  })
})
