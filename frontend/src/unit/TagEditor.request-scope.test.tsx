/**
 * Request-scope regressions for inline tag editing (#4501).
 *
 * The editor is mounted closed on detail surfaces so its open/close animation
 * and focus state stay local. It must not spend a request on the usable-tag
 * catalog until the reader actually opens it, and an open editor must read that
 * catalog exactly once. The bulk toolbar has the same rule for an empty
 * selection.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TagSection } from '../components/Tags/TagSection'
import { BulkTagToolbar } from '../components/Tags/BulkTagToolbar'
import { setDefaultHttpClient } from '../services/httpClient'
import { createRequestRecorder, requestCounts } from './requestRecorder'

const threadTags = {
  target_type: 'Thread',
  target_id: 42,
  direct_tags: [],
  effective_tags: [],
}

function renderTagSection() {
  return render(
    <TagSection targetType="Thread" targetId={42} targetLabel="Saga" />,
  )
}

describe('tag editor request scope', () => {
  it('does not read the catalog while closed and reads it exactly once on open', async () => {
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v1/tags/effective/thread/42/') return threadTags
      if (call.url === '/v1/tags/') return { tags: [] }
      return {}
    })
    setDefaultHttpClient(client)

    renderTagSection()

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/tags/effective/thread/42/')).toBe(true))
    expect(calls.some((call) => call.url === '/v1/tags/')).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'Edit tags' }))

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/tags/')).toBe(true))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)['GET /v1/tags/']).toBe(1)
  })

  it('bulk toolbar reads the catalog only for a non-empty selection, exactly once', async () => {
    const { calls, client } = createRequestRecorder((call) => {
      if (call.url === '/v1/tags/') return { tags: [] }
      return {}
    })
    setDefaultHttpClient(client)

    const view = render(
      <BulkTagToolbar selectedIds={[]} onClearSelection={() => undefined} />,
    )
    expect(calls.some((call) => call.url === '/v1/tags/')).toBe(false)

    view.rerender(
      <BulkTagToolbar selectedIds={[7]} onClearSelection={() => undefined} />,
    )

    await waitFor(() => expect(calls.some((call) => call.url === '/v1/tags/')).toBe(true))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(requestCounts(calls)['GET /v1/tags/']).toBe(1)
  })
})
