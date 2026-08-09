import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WhatsNewPage, { buildChangelogView, parseChangelog } from '../pages/WhatsNewPage'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('parseChangelog', () => {
  it('parses headings, paragraphs, both list markers, blank lines, and a trailing list', () => {
    expect(parseChangelog('# Changelog\n\nIntro paragraph\n## 2026-08-06\n- First item\n* Second item\n\n### Details\nFinal paragraph\n- Trailing item')).toEqual([
      { type: 'heading', level: 1, text: 'Changelog' },
      { type: 'paragraph', text: 'Intro paragraph' },
      { type: 'heading', level: 2, text: '2026-08-06' },
      { type: 'list', items: ['First item', 'Second item'] },
      { type: 'heading', level: 3, text: 'Details' },
      { type: 'paragraph', text: 'Final paragraph' },
      { type: 'list', items: ['Trailing item'] },
    ])
  })
})

describe('buildChangelogView', () => {
  it('groups multiple entries under one day and summarizes public feature areas', () => {
    expect(buildChangelogView('# Changelog\n\n## 2026-08-09\n### Queue\n- Faster loading\n- Clearer controls\n### Roll\n- Preserves the active comic', 'UTC')).toEqual([
      { type: 'heading', level: 1, text: 'Changelog' },
      { type: 'day', sourceDateTime: '2026-08-09', label: 'August 9, 2026', summary: '3 updates across Queue and Roll.', blocks: [
        { type: 'heading', level: 3, text: 'Queue' },
        { type: 'list', items: ['Faster loading', 'Clearer controls'] },
        { type: 'heading', level: 3, text: 'Roll' },
        { type: 'list', items: ['Preserves the active comic'] },
      ] },
    ])
  })

  it('covers singular, unscoped, and many-area daily summaries', () => {
    expect(buildChangelogView('## 2026-08-09\n### Queue\nOne change', 'UTC')[0]).toHaveProperty('summary', '1 update for Queue.')
    expect(buildChangelogView('## 2026-08-09\nOne change', 'UTC')[0]).toHaveProperty('summary', '1 update published this day.')
    expect(buildChangelogView('## 2026-08-09\n### Queue\n- A\n### Roll\n- B\n### Sessions\n- C', 'UTC')[0]).toHaveProperty('summary', '3 updates across Queue, Roll, and more.')
    expect(buildChangelogView('## 2026-08-09\n### Queue', 'UTC')[0]).toHaveProperty('summary', '1 update for Queue.')
  })

  it('uses the viewer timezone for exact source timestamps', () => {
    const view = buildChangelogView('## 2026-08-09T00:30:00Z\n### Roll\n- Fixed resume behavior', 'America/Los_Angeles')
    expect(view[0]).toMatchObject({ type: 'day', sourceDateTime: '2026-08-09T00:30:00Z' })
    expect(view[0]).toHaveProperty('label', 'August 8, 2026 at 5:30 PM PDT')
  })

  it('keeps malformed or missing timestamps usable as ordinary headings', () => {
    expect(buildChangelogView('## Recently\n- Still readable')).toEqual([
      { type: 'heading', level: 2, text: 'Recently' },
      { type: 'list', items: ['Still readable'] },
    ])
    expect(buildChangelogView('## 2026-99-99T99:99Z\n- Still readable')).toEqual([
      { type: 'heading', level: 2, text: '2026-99-99T99:99Z' },
      { type: 'list', items: ['Still readable'] },
    ])
  })
})

describe('WhatsNewPage', () => {
  it('groups dated entries with readable time elements and daily summaries', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => '# Changelog\n\n## 2026-08-09\n### Queue\n- Faster loading\n- Clearer controls\n### Roll\n- Preserves the active comic' })
    vi.stubGlobal('fetch', fetchMock)
    render(<WhatsNewPage />)
    const dayHeading = await screen.findByRole('heading', { name: /August 9, 2026/ })
    expect(dayHeading.querySelector('time')).toHaveAttribute('datetime', '2026-08-09')
    expect(screen.getByText('3 updates across Queue and Roll.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Queue' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Roll' })).toBeInTheDocument()
  })

  it('removes GitHub pull references while preserving public external links', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => '# Changelog\n\nPlain introduction.\n\n## Today\n\n### Queue\n\n- Fixed `Queue` in [#866](https://github.com/JoshCLWren/comic-pile/pull/866). See [ComicPile](https://comic-pile.vercel.app/) for more. [Internal notes](https://github.com/JoshCLWren/comic-pile/issues/981).' })
    vi.stubGlobal('fetch', fetchMock)
    render(<WhatsNewPage />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading release notes')
    expect(fetchMock).toHaveBeenCalledWith('/changelog.md', { cache: 'no-cache' })
    expect(await screen.findByRole('heading', { name: 'Changelog' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Today' }).tagName).toBe('H2')
    expect(screen.getByRole('heading', { name: 'Queue' }).tagName).toBe('H3')
    expect(screen.getByText('Plain introduction.')).toBeInTheDocument()
    expect(screen.getByText('Queue', { selector: 'code' })).toBeInTheDocument()
    expect(screen.getByRole('listitem')).not.toHaveTextContent('#866')
    expect(screen.getByRole('listitem')).toHaveTextContent(/Fixed Queue\. See ComicPile.*for more\./)
    expect(screen.queryByRole('link', { name: /#866/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Internal notes/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Internal notes/ })).not.toBeInTheDocument()
    const link = screen.getByRole('link', { name: /ComicPile/ })
    expect(link).toHaveAttribute('href', 'https://comic-pile.vercel.app/')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(screen.getByLabelText('opens in a new tab')).toBeInTheDocument()
  })

  it('distinguishes a missing changelog from other HTTP failures', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false, status: 404 }).mockResolvedValueOnce({ ok: false, status: 500 })
    vi.stubGlobal('fetch', fetchMock)
    render(<WhatsNewPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('changelog file is missing')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('reports an empty successful response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, text: async () => '  \n ' }))
    render(<WhatsNewPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('changelog file is empty')
  })

  it('reports thrown Error objects and recovers on retry', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error('network unavailable')).mockResolvedValueOnce({ ok: true, text: async () => '## Recovered' })
    vi.stubGlobal('fetch', fetchMock)
    render(<WhatsNewPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('network unavailable')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(await screen.findByRole('heading', { name: 'Recovered' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('uses the safe fallback for non-Error rejections', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('offline'))
    render(<WhatsNewPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
  })
})
