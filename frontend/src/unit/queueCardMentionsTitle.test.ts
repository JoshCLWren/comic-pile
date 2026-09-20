import { describe, expect, it } from 'vitest'
import { queueCardMentionsTitle } from '../test/queueCardTitle'

describe('queueCardMentionsTitle', () => {
  it('matches the exact thread number and rejects later pages with the same prefix', () => {
    expect(queueCardMentionsTitle('Open Test Thread 40 details', 'Test Thread 40')).toBe(true)
    expect(queueCardMentionsTitle('Open Test Thread 140 details', 'Test Thread 40')).toBe(false)
    expect(queueCardMentionsTitle('Open Test Thread 240 details', 'Test Thread 40')).toBe(false)
    expect(queueCardMentionsTitle('Open Test Thread 1 details', 'Test Thread 1')).toBe(true)
    expect(queueCardMentionsTitle('Open Test Thread 10 details', 'Test Thread 1')).toBe(false)
  })
})
