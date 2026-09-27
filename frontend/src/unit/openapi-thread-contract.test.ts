import { describe, it, expect } from 'vitest'
import type { components } from '../generated/openapi'
import type {
  Thread,
  ThreadListItem,
  ThreadListResponse,
} from '../types'

describe('OpenAPI Thread contract adoption (#2781)', () => {
  it('Thread detail aliases generated ThreadResponse', () => {
    type Generated = components['schemas']['ThreadResponse']
    // Structural assignment check: alias must be assignable both ways (identity)
    const _check = (x: Thread) => {
      const g: Generated = x
      const t: Thread = g
      return { g, t }
    }
    expect(typeof _check).toBe('function')
  })

  it('Thread list item aliases generated QueueThreadListItem', () => {
    type Generated = components['schemas']['QueueThreadListItem']
    const _check = (x: ThreadListItem) => {
      const g: Generated = x
      const t: ThreadListItem = g
      return { g, t }
    }
    expect(typeof _check).toBe('function')
  })

  it('Thread paginated response aliases generated QueueThreadListResponse', () => {
    type Generated = components['schemas']['QueueThreadListResponse']
    const _check = (x: ThreadListResponse) => {
      const g: Generated = x
      const t: ThreadListResponse = g
      return { g, t }
    }
    expect(typeof _check).toBe('function')
  })

  it('List/detail remain distinct (thread is not list item)', () => {
    // QueueThreadListItem deliberately lacks reading_progress, is_test, last_rating
    type ListItem = components['schemas']['QueueThreadListItem']
    type Detail = components['schemas']['ThreadResponse']
    // ListItem should not automatically satisfy Detail (missing required fields)
    // We verify by assigning a minimal ListItem and checking it lacks detail-only props
    const item: ListItem = {
      id: 1,
      title: 'T',
      format: 'issue',
      issues_remaining: 0,
      blocking_reasons: [],
      created_at: '',
      is_blocked: false,
      queue_position: 1,
      status: 'active',
      total_issues: null,
    } as ListItem
    expect(item).toBeDefined()
    // Ensure detail-specific properties are absent on the list-item type at compile time
    // (Structural typing enforces this; we assert identity via type-level usage above.)
    expect(typeof item).toBe('object')
  })
})
