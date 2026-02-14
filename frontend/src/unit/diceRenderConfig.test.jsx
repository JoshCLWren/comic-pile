import { expect, it } from 'vitest'
import {
  DEFAULT_DICE_RENDER_CONFIG,
  getDiceRenderConfigForSides,
} from '../components/diceRenderConfig'

it('returns default config when no overrides are provided', () => {
  const config = getDiceRenderConfigForSides(20)

  expect(config.uvInset).toBe(DEFAULT_DICE_RENDER_CONFIG.global.uvInset)
  expect(config.fontScale).toBe(DEFAULT_DICE_RENDER_CONFIG.global.fontScale)
  expect(config.triangleUvRadius).toBe(DEFAULT_DICE_RENDER_CONFIG.global.triangleUvRadius)
  expect(config.d10AutoCenter).toBe(DEFAULT_DICE_RENDER_CONFIG.global.d10AutoCenter)
})

it('applies global overrides', () => {
  const config = getDiceRenderConfigForSides(6, {
    global: {
      uvInset: 0.12,
      fontScale: 0.5,
      textOffsetX: 0.07,
    },
  })

  expect(config.uvInset).toBe(0.12)
  expect(config.fontScale).toBe(0.5)
  expect(config.textOffsetX).toBe(0.07)
})

it('applies per-side overrides over global values', () => {
  const config = getDiceRenderConfigForSides(20, {
    global: {
      uvInset: 0.08,
    },
    perSides: {
      '20': {
        uvInset: 0.16,
      },
    },
  })

  expect(config.uvInset).toBe(0.16)
})

it('uses committed per-side defaults', () => {
  const d10 = getDiceRenderConfigForSides(10)
  const d6 = getDiceRenderConfigForSides(6)

  expect(d10.uvInset).toBe(0.1)
  expect(d10.d10UvPadding).toBe(0.06)
  expect(d6.fontScale).toBe(0.58)
  expect(d6.textOffsetY).toBe(0.04)
})

it('clamps invalid values to safe ranges', () => {
  const config = getDiceRenderConfigForSides(10, {
    global: {
      tileSize: 255.7,
      uvInset: 9,
      fontScale: -3,
      borderWidth: 7.6,
      d10UvPadding: -5,
      d10TopOffsetX: 8,
      d10BottomOffsetY: -9,
    },
  })

  expect(config.tileSize).toBe(256)
  expect(config.uvInset).toBe(0.25)
  expect(config.fontScale).toBe(0.1)
  expect(config.borderWidth).toBe(8)
  expect(config.d10UvPadding).toBe(0)
  expect(config.d10TopOffsetX).toBe(0.5)
  expect(config.d10BottomOffsetY).toBe(-0.5)
})
