import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type { Thread, ThreadListItem, ThreadListResponse } from '../types'

type ThreadDetail = components['schemas']['ThreadResponse']
type QueueThreadListItem = components['schemas']['QueueThreadListItem']
type QueueThreadListResponse = components['schemas']['QueueThreadListResponse']

describe('OpenAPI Thread contract adoption (#2781)', () => {
  it('exports the thread detail response from OpenAPI', () => {
    expectTypeOf<Thread>().toEqualTypeOf<ThreadDetail>()
  })

  it('exports the queue thread list item from OpenAPI', () => {
    expectTypeOf<ThreadListItem>().toEqualTypeOf<QueueThreadListItem>()
  })

  it('exports the paginated queue thread list response from OpenAPI', () => {
    expectTypeOf<ThreadListResponse>().toEqualTypeOf<QueueThreadListResponse>()
    expectTypeOf<ThreadListResponse['threads']>().toEqualTypeOf<QueueThreadListItem[]>()
  })

  it('keeps the list item and the detail response distinct', () => {
    // The queue list endpoint deliberately omits the detail-only fields, so the
    // two generated schemas must not be interchangeable.
    expectTypeOf<QueueThreadListItem>().not.toEqualTypeOf<ThreadDetail>()
    expectTypeOf<ThreadDetail['is_test']>().toEqualTypeOf<boolean>()
    expectTypeOf<ThreadDetail['last_rating']>().toEqualTypeOf<number | null>()
    expectTypeOf<QueueThreadListItem>().not.toHaveProperty('is_test')
    expectTypeOf<QueueThreadListItem>().not.toHaveProperty('last_rating')
  })

  it('keeps the authoritative active count on the list response (#2568)', () => {
    expectTypeOf<ThreadListResponse['active_count']>().toEqualTypeOf<number>()
  })
})
