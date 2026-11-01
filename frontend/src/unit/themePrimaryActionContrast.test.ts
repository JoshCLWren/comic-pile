import { describe, expect, it } from 'vitest'
import styles from '../styles.css?raw'

function themeToken(theme: string, name: string): string {
  const block = styles.match(new RegExp(`\\[data-theme="${theme}"\\] \\{([\\s\\S]*?)\\n\\}`))?.[1]
  const value = block?.match(new RegExp(`\\s${name}: ([^;]+);`))?.[1]?.trim()
  if (!value) throw new Error(`Missing ${name} for theme ${theme}`)

  const referencedToken = value.match(/^var\((--[\w-]+)\)$/)?.[1]
  return referencedToken ? themeToken(theme, referencedToken) : value
}

function luminance(color: string): number {
  const hex = color.match(/^#([0-9a-f]{6})$/i)?.[1]
  if (!hex) throw new Error(`Expected six-digit hex, got ${color}`)
  const linear = [0, 2, 4].map((offset) => {
    const channel = parseInt(hex.slice(offset, offset + 2), 16) / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
}

function contrastRatio(first: string, second: string): number {
  const light = Math.max(luminance(first), luminance(second))
  const dark = Math.min(luminance(first), luminance(second))
  return (light + 0.05) / (dark + 0.05)
}

describe.each(['classic', 'ink-gold', 'command-center'])('%s primary action contrast', (theme) => {
  it.each(['--theme-primary-action', '--theme-primary-action-hover'])(
    'keeps readable text on %s',
    (backgroundToken) => {
      expect(
        contrastRatio(
          themeToken(theme, '--theme-primary-action-text'),
          themeToken(theme, backgroundToken),
        ),
      ).toBeGreaterThanOrEqual(4.5)
    },
  )
})
