import { readFileSync } from 'node:fs'
import path from 'node:path'
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import WhatsNewPage, { parseChangelog } from './WhatsNewPage'

const frontendRoot = path.resolve(import.meta.dirname, '../..')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('parseChangelog', () => {
  it('preserves headings, lists, code, and links as structured blocks', () => {
    expect(parseChangelog('## 2026-08-06\n\n- Added `Roll` ([#866](https://github.com/JoshCLWren/comic-pile/pull/866)).')).toEqual([
      { type: 'heading', level: 2, text: '2026-08-06' },
      { type: 'list', items: ['Added `Roll` ([#866](https://github.com/JoshCLWren/comic-pile/pull/866)).'] },
    ])
  })
})

describe('WhatsNewPage', () => {
  it('renders the static changelog and external PR links', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: async () => '## Today\n\n- Fixed `Queue` in [#866](https://github.com/JoshCLWren/comic-pile/pull/866).' })
    vi.stubGlobal('fetch', fetchMock)
    render(<WhatsNewPage />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading release notes')
    expect(fetchMock).toHaveBeenCalledWith('/changelog.md', { cache: 'no-cache' })
    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /#866/ })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
  })

  it('shows a useful error and retries the static request', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: true, text: async () => '## Recovered' })
    vi.stubGlobal('fetch', fetchMock)
    render(<WhatsNewPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('missing')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/changelog.md', { cache: 'no-cache' })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/changelog.md', { cache: 'no-cache' })
    expect(await screen.findByRole('heading', { name: 'Recovered' })).toBeInTheDocument()
  })

  it('keeps the authenticated route and More-menu link wired to the page', () => {
    const appSource = readFileSync(path.join(frontendRoot, 'src/App.tsx'), 'utf-8')
    const navigationSource = readFileSync(path.join(frontendRoot, 'src/components/Navigation.tsx'), 'utf-8')

    expect(appSource).toContain('path="/whats-new"')
    expect(appSource).toContain('<WhatsNewPage />')
    expect(navigationSource).toContain('to="/whats-new"')
    expect(navigationSource).toContain('What’s New')
  })

  it('keeps the canonical changelog wired to the production static asset', () => {
    const viteConfigSource = readFileSync(path.join(frontendRoot, 'vite.config.ts'), 'utf-8')
    const changelogSource = readFileSync(path.resolve(frontendRoot, '../docs/changelog.md'), 'utf-8')

    expect(changelogSource).toMatch(/^# Changelog/m)
    expect(viteConfigSource).toContain("const changelogPath = path.resolve(__dirname, '../docs/changelog.md')")
    expect(viteConfigSource).toContain("fileName: 'changelog.md'")
    expect(viteConfigSource).toContain('source: changelogSource')
  })
})
