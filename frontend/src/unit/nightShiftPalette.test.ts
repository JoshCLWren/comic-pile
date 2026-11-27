/**
 * Night Shift is the sole visual identity (#5980). These guards replace the
 * retired multi-theme runtime/surface tests with a one-palette contract:
 * a single semantic token set, exact approved colors, legacy aliases that
 * point at that set, and WCAG AA contrast for text and status roles.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function readFrontendFile(relativePath: string): string {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8')
}

function readVisualGrammar(): string {
  let directory = process.cwd()
  for (let depth = 0; depth < 4; depth += 1) {
    const candidate = resolve(directory, 'docs', 'FRONTEND_VISUAL_GRAMMAR.md')
    if (existsSync(candidate)) return readFileSync(candidate, 'utf8')
    directory = resolve(directory, '..')
  }
  throw new Error('docs/FRONTEND_VISUAL_GRAMMAR.md was not found above the frontend package')
}

function rootBlock(css: string): string {
  const start = css.indexOf(':root {')
  expect(start, 'canonical :root token set missing').toBeGreaterThanOrEqual(0)
  const open = css.indexOf('{', start)
  const close = css.indexOf('\n}', open)
  expect(close, 'unterminated :root block').toBeGreaterThan(open)
  return css.slice(open + 1, close)
}

function tokenMap(block: string): Map<string, string> {
  const map = new Map<string, string>()
  for (const match of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    map.set(match[1], match[2].trim())
  }
  return map
}

function resolveToken(tokens: Map<string, string>, name: string): string {
  const value = tokens.get(name)
  expect(value, `missing ${name}`).toBeTruthy()
  const referenced = value?.match(/^var\((--[\w-]+)\)$/)?.[1]
  // SAFETY: a referenced token is resolved from the same complete :root map
  return referenced ? resolveToken(tokens, referenced) : (value as string)
}

function luminance(color: string): number {
  const hex = color.match(/^#([0-9a-f]{6})$/i)?.[1]
  if (!hex) throw new Error(`Expected six-digit hex, got ${color}`)
  const channels = [0, 2, 4].map((offset) => {
    const channel = parseInt(hex.slice(offset, offset + 2), 16) / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrastRatio(first: string, second: string): number {
  const light = Math.max(luminance(first), luminance(second))
  const dark = Math.min(luminance(first), luminance(second))
  return (light + 0.05) / (dark + 0.05)
}

function collectConsumedThemeTokens(): Set<string> {
  const tokens = new Set<string>()
  const visit = (directory: string): void => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name)
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules' && entry.name !== 'generated') visit(path)
        continue
      }
      if (!/\.(?:ts|tsx|css)$/.test(entry.name)) continue
      if (/\.(?:test|spec)\.(?:ts|tsx)$/.test(entry.name)) continue
      const source = readFileSync(path, 'utf8')
      for (const match of source.matchAll(/--theme-[a-z0-9]+(?:-[a-z0-9]+)*/g)) {
        tokens.add(match[0])
      }
    }
  }
  visit(resolve(process.cwd(), 'src'))
  return tokens
}

const styles = readFrontendFile('src/styles.css')
const tokens = tokenMap(rootBlock(styles))

describe('Night Shift single-palette contract (#5980)', () => {
  it('uses the approved prototype colors for the canonical roles', () => {
    const expected: Record<string, string> = {
      '--theme-bg-page': '#20242d',
      '--theme-bg-panel': '#303644',
      '--theme-text-primary': '#eef1f4',
      '--theme-text-muted': '#b2bdcb',
      '--theme-comic-accent': '#9cdbe9',
      '--theme-continuity-accent': '#c1a7f5',
      '--theme-border': '#4d5767',
      '--theme-primary-action-text': '#111111',
      '--die-light': '#c2e9f1',
      '--die-dark': '#658e97',
    }
    for (const [token, value] of Object.entries(expected)) {
      expect(resolveToken(tokens, token).toLowerCase(), token).toBe(value)
    }
  })

  it('declares every consumed --theme-* role in the one canonical set', () => {
    const consumed = collectConsumedThemeTokens()
    expect(consumed.size).toBeGreaterThan(0)
    expect(consumed.has('--theme-bg-hover'), 'hover role must be consumed by source').toBe(true)
    for (const token of consumed) {
      expect(tokens.get(token), `${token} is consumed but not declared`).toBeTruthy()
    }
  })

  it('points legacy aliases at the canonical semantic roles', () => {
    const aliases: Record<string, string> = {
      '--bg-main': 'var(--theme-bg-page)',
      '--bg-darker': 'var(--theme-bg-panel)',
      '--text-primary': 'var(--theme-text-primary)',
      '--text-muted': 'var(--theme-text-muted)',
      '--text-dim': 'var(--theme-text-dim)',
      '--accent-primary': 'var(--theme-comic-accent)',
      '--accent-red': 'var(--theme-danger)',
      '--glass-bg': 'var(--theme-bg-panel)',
      '--glass-border': 'var(--theme-border)',
      '--theme-text': 'var(--theme-text-primary)',
    }
    for (const [alias, target] of Object.entries(aliases)) {
      expect(tokens.get(alias), alias).toBe(target)
    }
  })

  it('keeps comic, continuity and personal accents distinct concrete colors', () => {
    const accents = ['--theme-comic-accent', '--theme-continuity-accent', '--theme-personal-accent']
      .map((token) => resolveToken(tokens, token).toLowerCase())
    expect(new Set(accents).size).toBe(accents.length)
    for (const accent of accents) {
      expect(accent).toMatch(/^#[0-9a-f]{6}$/)
    }
  })

  it('keeps status roles semantically separate from the primary action', () => {
    const primary = resolveToken(tokens, '--theme-primary-action').toLowerCase()
    for (const token of ['--theme-danger', '--theme-error', '--theme-warning', '--theme-success']) {
      expect(resolveToken(tokens, token).toLowerCase(), token).not.toBe(primary)
    }
    expect(resolveToken(tokens, '--theme-danger-hover')).not.toBe(
      resolveToken(tokens, '--theme-danger'),
    )
  })

  it('renders text and status colors at WCAG AA contrast on page and panel', () => {
    const page = resolveToken(tokens, '--theme-bg-page')
    const panel = resolveToken(tokens, '--theme-bg-panel')
    const textRoles = [
      '--theme-text-primary',
      '--theme-text-muted',
      '--theme-text-dim',
      '--theme-comic-accent',
      '--theme-continuity-accent',
      '--theme-personal-accent',
      '--theme-warning',
      '--theme-success',
      '--theme-error',
      '--theme-danger',
    ]
    for (const token of textRoles) {
      const color = resolveToken(tokens, token)
      expect(contrastRatio(color, page), `${token} on page`).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(color, panel), `${token} on panel`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps the primary-action foreground readable in both action states', () => {
    const foreground = resolveToken(tokens, '--theme-primary-action-text')
    for (const token of ['--theme-primary-action', '--theme-primary-action-hover']) {
      expect(contrastRatio(foreground, resolveToken(tokens, token)), token).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('documents every canonical role in the visual grammar', () => {
    const grammar = readVisualGrammar()
    for (const [token] of tokens) {
      if (token.startsWith('--theme-')) {
        expect(grammar, `${token} must be documented`).toContain(token)
      }
    }
  })

  it('has no selectable theme, data-theme switch, or legacy palette literals', () => {
    expect(styles).not.toMatch(/\[data-theme\s*=/)
    for (const retired of ['classic', 'ink-gold', 'command-center']) {
      expect(styles).not.toContain(retired)
    }
    for (const legacy of ['#1a1410', '#d4890e', '#e8d5b0', '#a0937e', '#c0392b', '#2a2018', '#110e0a']) {
      expect(styles.toLowerCase()).not.toContain(legacy)
    }
  })
})

describe('Night Shift boot and storage contract (#5980)', () => {
  const sourceRoot = resolve(process.cwd(), 'src')

  it('never restores or writes an appearance preference', () => {
    const visit = (directory: string): string[] => {
      const files: string[] = []
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = resolve(directory, entry.name)
        if (entry.isDirectory()) {
          if (entry.name !== 'node_modules' && entry.name !== 'generated') files.push(...visit(path))
          continue
        }
        if (/\.(?:ts|tsx)$/.test(entry.name) && !/\.(?:test|spec)\./.test(entry.name)) {
          files.push(path)
        }
      }
      return files
    }
    for (const path of visit(sourceRoot)) {
      const source = readFileSync(path, 'utf8')
      expect(source, `${path} must not read or write theme storage`).not.toContain('comic-pile-theme')
      expect(source, `${path} must not set data-theme`).not.toContain("setAttribute('data-theme'")
    }
  })

  it('applies Night Shift colors in the inline bootstrap shell', () => {
    const shell = readFrontendFile('index.html')
    for (const color of ['#20242d', '#303644', '#eef1f4', '#b2bdcb', '#9cdbe9', '#4d5767']) {
      expect(shell.toLowerCase(), `bootstrap shell needs ${color}`).toContain(color)
    }
    expect(shell).not.toContain('#2b2118')
    expect(shell).not.toContain('#d4a35f')
    expect(shell).not.toMatch(/data-theme|localStorage/)
  })
})
