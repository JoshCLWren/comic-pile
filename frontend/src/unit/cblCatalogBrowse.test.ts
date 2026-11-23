import { describe, expect, it } from 'vitest'
import {
  catalogSourceCount,
  catalogTotalLabel,
  isStaleBrowsePosition,
} from '../utils/cblCatalogBrowse'

describe('catalogSourceCount', () => {
  it('adds recursive folder counts to direct sources', () => {
    expect(catalogSourceCount([{ total_list_count: 40 }, { total_list_count: 97 }], 1)).toBe(138)
  })

  it('keeps the direct total when no folders are shown', () => {
    expect(catalogSourceCount([], 137)).toBe(137)
  })
})

describe('catalogTotalLabel', () => {
  it('pluralizes sources and folders', () => {
    expect(catalogTotalLabel(1, 1)).toBe('1 source in the shared CBL catalog across 1 folder')
    expect(catalogTotalLabel(138, 2)).toBe('138 sources in the shared CBL catalog across 2 folders')
  })

  it('omits folder detail when none are shown', () => {
    expect(catalogTotalLabel(137, 0)).toBe('137 sources in the shared CBL catalog')
  })
})

describe('isStaleBrowsePosition', () => {
  const root = { scope: 'folder', query: null, folder: '', page: 1 }
  const search = (query: string) => ({ scope: 'search', query, folder: '', page: 1 })

  it('never marks settled or not-yet-loaded data stale', () => {
    expect(isStaleBrowsePosition(root, false, '', 'Batman', 1)).toBe(false)
    expect(isStaleBrowsePosition(null, true, '', 'Batman', 1)).toBe(false)
  })

  it('hides root folders while a search loads', () => {
    expect(isStaleBrowsePosition(root, true, '', 'Batman', 1)).toBe(true)
  })

  it('hides an older search while a new one loads', () => {
    expect(isStaleBrowsePosition(search('ultimate'), true, '', 'Batman', 1)).toBe(true)
  })

  it('keeps a matching search or folder visible while fetching', () => {
    expect(isStaleBrowsePosition(search('Batman'), true, '', 'Batman', 1)).toBe(false)
    expect(isStaleBrowsePosition({ ...root, folder: 'Marvel' }, true, 'Marvel', '', 1)).toBe(false)
  })

  it('hides an obsolete folder while a new one loads', () => {
    expect(isStaleBrowsePosition(root, true, 'Marvel', '', 1)).toBe(true)
  })

  it('hides an obsolete page while a new page loads', () => {
    expect(isStaleBrowsePosition({ ...root, page: 1 }, true, '', '', 2)).toBe(true)
    expect(isStaleBrowsePosition({ ...root, page: 2 }, true, '', '', 2)).toBe(false)
  })
})
