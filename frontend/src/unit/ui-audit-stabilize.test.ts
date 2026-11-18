import { describe, expect, it } from 'vitest'
import {
  AUDIT_FIXED_NOW,
  AUDIT_FIXED_USERNAME,
  stabilizeAuditApiPayload,
} from '../test/ui-audit/stabilize'

describe('UI audit fixture stabilization', () => {
  it('normalizes the generated username without mutating the server payload', () => {
    const payload = { id: 17, username: 'auth_threads_1788100000000_1_9912', email: 'reader@example.com' }

    const stabilized = stabilizeAuditApiPayload('/api/v2/auth/me', payload)

    expect(stabilized).toEqual({ ...payload, username: AUDIT_FIXED_USERNAME })
    expect(payload.username).toBe('auth_threads_1788100000000_1_9912')
  })

  it('normalizes user-visible session timestamps while preserving session shape', () => {
    const payload = {
      sessions: [
        {
          id: 42,
          started_at: '2026-08-30T17:13:19.000Z',
          ended_at: '2026-08-30T17:16:04.000Z',
          created_at: '2026-08-30T17:13:19.000Z',
          updated_at: '2026-08-30T17:16:04.000Z',
          snapshot_count: 1,
        },
        {
          id: 43,
          started_at: '2026-08-30T17:18:19.000Z',
          ended_at: null,
          snapshot_count: 0,
        },
      ],
      next_page_token: null,
    }

    const stabilized = stabilizeAuditApiPayload('/api/v1/sessions/', payload)

    expect(stabilized).toEqual({
      sessions: [
        {
          ...payload.sessions[0],
          started_at: AUDIT_FIXED_NOW,
          ended_at: '2026-08-30T12:15:00.000Z',
          created_at: AUDIT_FIXED_NOW,
          updated_at: '2026-08-30T12:15:00.000Z',
        },
        {
          ...payload.sessions[1],
          started_at: '2026-08-30T12:01:00.000Z',
          ended_at: null,
        },
      ],
      next_page_token: null,
    })
    expect(payload.sessions[0].started_at).toBe('2026-08-30T17:13:19.000Z')
  })

  it('normalizes activity timestamps without mutating the server payload', () => {
    const entries = [
      {
        event_id: 501,
        type: 'snooze',
        timestamp: '2026-11-08T15:46:25.515000Z',
        die_before: 6,
        die_after: 8,
      },
      {
        event_id: 502,
        type: 'roll',
        timestamp: '2026-11-08T15:46:25.467000Z',
        die_before: 8,
      },
    ]
    const payload = {
      activities: entries,
      events: entries,
      items: entries,
      next_page_token: null,
      next_cursor: null,
    }

    const stabilized = stabilizeAuditApiPayload('/api/v2/activity', payload)

    expect(stabilized).toEqual({
      ...payload,
      activities: [
        { ...entries[0], timestamp: AUDIT_FIXED_NOW },
        { ...entries[1], timestamp: '2026-08-30T12:01:00.000Z' },
      ],
      events: [
        { ...entries[0], timestamp: AUDIT_FIXED_NOW },
        { ...entries[1], timestamp: '2026-08-30T12:01:00.000Z' },
      ],
      items: [
        { ...entries[0], timestamp: AUDIT_FIXED_NOW },
        { ...entries[1], timestamp: '2026-08-30T12:01:00.000Z' },
      ],
    })
    expect(payload.items[0].timestamp).toBe('2026-11-08T15:46:25.515000Z')
  })

  it('leaves unrelated API payloads untouched', () => {
    const payload = { value: 'unchanged' }

    expect(stabilizeAuditApiPayload('/api/v1/queue/', payload)).toBe(payload)
  })
})
