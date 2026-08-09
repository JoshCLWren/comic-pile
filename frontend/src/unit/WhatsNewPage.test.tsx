import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WhatsNewPage, { parseChangelog } from '../pages/WhatsNewPage'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('parseChangelog', () => {
  it('parses headings, paragraphs, both list markers, blank lines, and a trailing list', () => {
    expect(
      parseChangelog(
        '# Changelog\n\nIntro paragraph\n## 2026-08-06\n- First item\n* Second item\n\n### Details\nFinal paragraph\n- Trailing item',
      ),
    ).toEqual([
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

describe('WhatsNewPage', () => {
  it('renders GitHub references as text while preserving public external links', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        '# Changelog\n\nPlain introduction.\n\n## Today\n\n### Queue\n\n- Fixed `Queue` in [#866](https://github.com/JoshCLWren/comic-pile/pull/866). See [ComicPile](https://comic-pile.vercel.app/) for more.',
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<WhatsNewPage />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading release notes')
    expect(fetchMock).toHaveBeenCalledWith('/changelog.md', { cache: 'no-cache' })
    expect(await screen.findByRole('heading', { name: 'Changelog' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Today' }).tagName).toBe('H2')
    expect(screen.getByRole('heading', { name: 'Queue' }).tagName).toBe('H3')
    expect(screen.getByText('Plain introduction.')).toBeInTheDocument()
    expect(screen.getByText('Queue', { selector: 'code' })).toBeInTheDocument()
    expect(screen.getByRole('listitem')).toHaveTextContent('#866')
    expect(screen.queryByRole('link', { name: /#866/ })).not.toBeInTheDocument()

    const link = screen.getByRole('link', { name: /ComicPile/ })
    expect(link).toHaveAttribute('href', 'https://comic-pile.vercel.app/')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(screen.getByLabelText('opens in a new tab')).toBeInTheDocument()
  })

  it('distinguishes a missing changelog from other HTTP failures', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: false, status: 500 })
    vi.stubGlobal('fetch', fetchMock)

    render(<WhatsNewPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('changelog file is missing')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('reports an empty successful response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, text: async () => '  \n ' }),
    )

    render(<WhatsNewPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('changelog file is empty')
  })

  it('reports thrown Error objects and recovers on retry', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce({ ok: true, text: async () => '## Recovered' })
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
