import { ReaderContextResponse } from '../types'

export const readerContextApi = {
  /**
   * Get reader context analytics for a specific issue
   * @param issueId - The issue ID to get reader context for
   * @returns Reader context response with series and crossover analytics
   */
  getReaderContext: async (issueId: number): Promise<ReaderContextResponse> => {
    return (await import('./api-issues')).issuesApi.getReaderContext(issueId)
  },
}