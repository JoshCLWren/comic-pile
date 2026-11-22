import { expect, it, vi } from 'vitest'
import * as formatters from '../utils/formatIssueCount'

it('checks whether Vitest supports spying on an ES module export', () => {
  const spy = vi.spyOn(formatters, 'formatIssueCount').mockReturnValue('stubbed')
  expect(formatters.formatIssueCount(1)).toBe('stubbed')
  spy.mockRestore()
})
