import { describe, expectTypeOf, it } from 'vitest'

import type { components } from '../generated/openapi'
import type { Thread, ThreadListItem, ThreadListResponse, ThreadQueueExclusionGroup } from '../types'

type ThreadDetail = components['schemas']['ThreadResponse']
type QueueThreadListItem = components['schemas']['QueueThreadListItem']
type QueueThreadListResponse = components['schemas']['QueueThreadListResponse']

describe('OpenAPI Thread contract adoption (#2781)', () => {
  it('exports the thread detail response from OpenAPI', () => {
    expectTypeOf<Thread>().toEqualTypeOf<ThreadDetail>()
  })

  it('exports the queue thread list item from OpenAPI plus native extensions', () => {
    // #5433 adds the native-only derived series cover and #5435 adds additive
    // exclusion-group provenance on excluded rows; the checked-in generated
    // OpenAPI schema is bot-owned and may lag runtime fields until regenerated.
    expectTypeOf<
      Omit<ThreadListItem, 'queue_exclusion_group' | 'series_cover_image_url'>
    >().toEqualTypeOf<QueueThreadListItem>()
    expectTypeOf<ThreadListItem['series_cover_image_url']>().toEqualTypeOf<string | null | undefined>()
    expectTypeOf<ThreadListItem['queue_exclusion_group']>().toEqualTypeOf<
      ThreadQueueExclusionGroup | null | undefined
    >()
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
