import { describe, expect, it } from 'vitest'

import { parseRequestedIssueId, threadIssueRoutePath } from '../utils/threadRoutes'

describe('threadIssueRoutePath', () => {
  it('builds the canonical issue deep link used by every issue entry point', () => {
    expect(threadIssueRoutePath(7, 11)).toBe('/thread/7?issue=11#issue-11')
  })

  it('falls back to plain thread navigation without a usable issue id', () => {
    expect(threadIssueRoutePath(7)).toBe('/thread/7')
    expect(threadIssueRoutePath(7, null)).toBe('/thread/7')
    expect(threadIssueRoutePath(7, 0)).toBe('/thread/7')
    expect(threadIssueRoutePath(7, 1.5)).toBe('/thread/7')
  })

  it('round-trips through the URL parser the Thread page uses', () => {
    const url = new URL(threadIssueRoutePath(42, 115), 'https://comic-pile.test')
    expect(url.pathname).toBe('/thread/42')
    expect(url.hash).toBe('#issue-115')
    expect(parseRequestedIssueId(url.search)).toBe(115)
  })
})

describe('parseRequestedIssueId', () => {
  it('reads a positive canonical issue id', () => {
    expect(parseRequestedIssueId('?issue=115')).toBe(115)
    expect(parseRequestedIssueId('?foo=1&issue=115&prerequisites=1')).toBe(115)
  })

  it('treats absent, empty, and malformed targets as plain thread navigation', () => {
    expect(parseRequestedIssueId('')).toBe(0)
    expect(parseRequestedIssueId('?issue=')).toBe(0)
    expect(parseRequestedIssueId('?issue=abc')).toBe(0)
    expect(parseRequestedIssueId('?issue=1.5')).toBe(0)
    expect(parseRequestedIssueId('?issue=-3')).toBe(0)
    expect(parseRequestedIssueId('?issue=0')).toBe(0)
  })
})
