import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import type { AuthContextValue } from '../App'
import { AuthProvider, useAuth } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { ToastProvider } from '../contexts/ToastProvider'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  clearAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  getAccessToken: vi.fn<() => string | null>(),
  readStoredAccessToken: vi.fn<() => string | null>(),
}))

vi.mock('../services/api', () => ({
  default: {
    get: mocks.get,
    post: mocks.post,
    patch: mocks.patch,
  },
  clearAccessToken: mocks.clearAccessToken,
  setAccessToken: mocks.setAccessToken,
  getAccessToken: mocks.getAccessToken,
  readStoredAccessToken: mocks.readStoredAccessToken,
  refreshSession: vi.fn(),
  isSessionRefreshRejected: () => false,
}))

const THEMES = ['classic', 'ink-gold', 'command-center'] as const

type ThemeId = (typeof THEMES)[number]

const SEMANTIC_TOKENS = [
  '--theme-bg-page',
  '--theme-bg-panel',
  '--theme-border',
  '--theme-text-primary',
  '--theme-text-muted',
  '--theme-text-dim',
  '--theme-comic-accent',
  '--theme-continuity-accent',
  '--theme-personal-accent',
  '--theme-primary-action',
  '--theme-danger',
  '--theme-focus-ring',
] as const

/**
 * Every legacy palette alias must re-point at its semantic theme token inside
 * each [data-theme] block (issue #1646): surfaces consuming the older
 * variables must reskin with the active theme instead of staying frozen in
 * classic colors.
 */
const ALIAS_CONTRACT: ReadonlyArray<readonly [alias: string, target: string]> = [
  ['--bg-main', 'var(--theme-bg-page)'],
  ['--text-primary', 'var(--theme-text-primary)'],
  ['--text-muted', 'var(--theme-text-muted)'],
  ['--text-dim', 'var(--theme-text-dim)'],
  ['--accent-primary', 'var(--theme-comic-accent)'],
  ['--accent-red', 'var(--theme-danger)'],
  ['--glass-bg', 'var(--theme-bg-panel)'],
  ['--glass-border', 'var(--theme-border)'],
]

function loadStylesheet(): string {
  // The Vitest jsdom runner can surface import.meta.url as the simulated page
  // origin (http://localhost:3000/) instead of a file URL, so anchor on file
  // URLs when available and otherwise resolve against the frontend root.
  const specifier = new URL('../styles.css', import.meta.url)
  const stylesheet =
    specifier.protocol === 'file:'
      ? fileURLToPath(specifier)
      : resolve(process.cwd(), 'src', 'styles.css')
  return readFileSync(stylesheet, 'utf8')
}

function extractThemeBlock(css: string, theme: ThemeId): string {
  const start = css.indexOf(`[data-theme="${theme}"]`)
  expect(start, `missing [data-theme="${theme}"] block`).toBeGreaterThanOrEqual(0)
  const openBrace = css.indexOf('{', start)
  const closeBrace = css.indexOf('\n}', openBrace)
  expect(closeBrace, `unterminated [data-theme="${theme}"] block`).toBeGreaterThan(openBrace)
  return css.slice(openBrace + 1, closeBrace)
}

function extractTokenMap(block: string): Map<string, string> {
  const map = new Map<string, string>()
  for (const match of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    map.set(match[1], match[2].trim())
  }
  return map
}

function tokenValuesPerTheme(css: string, token: string): string[] {
  return THEMES.map((theme) => {
    const value = extractTokenMap(extractThemeBlock(css, theme)).get(token)
    expect(value, `${token} missing for ${theme}`).toBeTruthy()
    return value as string
  })
}

function extractGradientBodyRule(css: string): string | undefined {
  const rules: string[] = []
  let start = css.indexOf('\nbody {')
  while (start >= 0) {
    const closeBrace = css.indexOf('}', start)
    if (closeBrace < 0) break
    rules.push(css.slice(start, closeBrace + 1))
    start = css.indexOf('\nbody {', closeBrace)
  }
  return rules.find((rule) => rule.includes('radial-gradient'))
}

describe('semantic theme stylesheet contract (#1646)', () => {
  it('defines every semantic token in all three themes', () => {
    const css = loadStylesheet()

    for (const theme of THEMES) {
      const tokens = extractTokenMap(extractThemeBlock(css, theme))
      for (const token of SEMANTIC_TOKENS) {
        expect(tokens.get(token), `${token} missing in ${theme}`).toBeTruthy()
      }
    }
  })

  it('re-points every legacy palette alias at its semantic token per theme', () => {
    const css = loadStylesheet()

    for (const theme of THEMES) {
      const tokens = extractTokenMap(extractThemeBlock(css, theme))
      for (const [alias, target] of ALIAS_CONTRACT) {
        expect(tokens.get(alias), `${alias} in ${theme}`).toBe(target)
      }
    }
  })

  it('gives each theme a distinct page canvas through the body gradient aliases', () => {
    const css = loadStylesheet()

    const bodyRule = extractGradientBodyRule(css)
    expect(bodyRule, 'gradient body rule missing').toBeTruthy()
    expect(bodyRule).toContain('var(--bg-glow)')
    expect(bodyRule).toContain('var(--bg-main)')
    expect(bodyRule).toContain('var(--bg-darker)')

    for (const token of ['--bg-glow', '--theme-bg-page', '--theme-comic-accent']) {
      const values = new Set(tokenValuesPerTheme(css, token))
      expect(values.size, `${token} must differ across all three themes`).toBe(THEMES.length)
    }
  })
})

describe('themed surfaces resolve through semantic tokens (#1646)', () => {
  let auth: AuthContextValue | null = null

  function AuthConsumer() {
    auth = useAuth()
    return null
  }

  beforeEach(() => {
    auth = null
    document.documentElement.setAttribute('data-theme', 'classic')
    localStorage.clear()
    mocks.get.mockReset()
    mocks.patch.mockReset()
    mocks.post.mockReset()
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
    mocks.getAccessToken.mockReturnValue('test-token')
  })

  function renderNavigationAtWidth(width: number) {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
    window.dispatchEvent(new Event('resize'))
    return render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <BugReportRestoreProvider>
            <ToastProvider>
              <Navigation onBugReportSubmit={vi.fn()} />
              <AuthConsumer />
            </ToastProvider>
          </BugReportRestoreProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
  }

  it('binds the More tray surfaces to semantic theme variables', async () => {
    const user = userEvent.setup()
    renderNavigationAtWidth(390)

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))

    await user.click(await screen.findByRole('button', { name: 'More pages' }))

    const tray = screen.getByRole('navigation', { name: 'More pages' })
    expect(tray.className).toContain('border-[var(--theme-border)]')
    expect(tray.className).toContain('bg-[var(--theme-bg-page)]')

    const appearanceHeading = within(tray).getByText('Appearance')
    expect(appearanceHeading.parentElement?.getAttribute('style')).toContain(
      'var(--theme-text-muted)',
    )

    for (const link of within(tray).getAllByRole('link')) {
      expect(link.className).toContain('text-[var(--theme-text-primary)]')
      expect(link.className).toContain('hover:bg-[var(--theme-bg-panel)]')
    }

    for (const name of ['Classic theme', 'Ink-gold theme', 'Command center theme']) {
      expect(within(tray).getByRole('button', { name }).className).toContain(
        'hover:bg-[var(--theme-bg-panel)]',
      )
    }
  })

  it('binds the desktop Appearance picker to semantic theme variables', async () => {
    renderNavigationAtWidth(1280)

    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))

    const group = screen.getByRole('group', { name: 'Appearance' })
    expect(group.className).toContain('border-[var(--theme-border)]')
    expect(group.className).toContain('bg-[var(--theme-bg-panel)]')
    expect(group.className).not.toContain('#110e0a')

    const label = group.querySelector('span')
    expect(label).not.toBeNull()
    expect(label?.getAttribute('style')).toContain('var(--theme-text-muted)')

    for (const button of group.querySelectorAll('button')) {
      const bindsActiveText = button.className.includes('text-[var(--theme-text-primary)]')
      const bindsInactiveText =
        button.className.includes('text-[var(--theme-text-muted)]') &&
        button.className.includes('hover:text-[var(--theme-text-primary)]')
      expect(bindsActiveText || bindsInactiveText).toBe(true)
      expect(button.className.includes('stone-')).toBe(false)
    }
  })
})
