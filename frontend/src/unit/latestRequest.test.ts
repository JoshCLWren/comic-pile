import { describe, expect, it } from 'vitest'
import { LatestRequestGuard } from '../utils/latestRequest'

describe('LatestRequestGuard', () => {
  it('issues a distinct ticket per request', () => {
    const guard = new LatestRequestGuard()

    const first = guard.begin()
    const second = guard.begin()

    expect(first).not.toBe(second)
    expect(guard.isCurrent(second)).toBe(true)
  })

  it('stops recognizing a ticket once a newer request begins', () => {
    const guard = new LatestRequestGuard()

    const first = guard.begin()
    guard.begin()

    expect(guard.isCurrent(first)).toBe(false)
  })

  it('stops recognizing an outstanding ticket after the surface is abandoned', () => {
    const guard = new LatestRequestGuard()

    const ticket = guard.begin()
    guard.abandon()

    expect(guard.isCurrent(ticket)).toBe(false)
  })

  it('never treats an unissued ticket as current', () => {
    const guard = new LatestRequestGuard()

    expect(guard.isCurrent(0)).toBe(false)
    guard.abandon()
    expect(guard.isCurrent(0)).toBe(false)
  })

  it('keeps the newest request current after another abandonment', () => {
    const guard = new LatestRequestGuard()

    guard.begin()
    guard.abandon()
    const ticket = guard.begin()
    guard.abandon()

    expect(guard.isCurrent(ticket)).toBe(false)
  })
})
