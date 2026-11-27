import { describe, expect, it } from 'vitest'
import {
  GALLERY_SWIPE_THRESHOLD,
  PRODUCTION_DICE_SIDES,
  allocateCoverFaces,
  carouselOffset,
  carouselTransform,
  computeCoverBoardLayout,
  galleryCoverWidth,
  getCoverArrangement,
  resolveProductionDie,
  wrapCarouselIndex,
} from '../pages/RollPage/coverBoardLayout'

describe('Night Shift cover-first board geometry (#5981)', () => {
  it('uses exactly the production dice and the approved arrangements', () => {
    expect([...PRODUCTION_DICE_SIDES]).toEqual([2, 4, 6, 8, 10, 12, 20])
    expect(getCoverArrangement(2)).toEqual([0, 2, 0])
    expect(getCoverArrangement(4)).toEqual([2, 0, 2])
    expect(getCoverArrangement(6)).toEqual([2, 2, 2])
    expect(getCoverArrangement(8)).toEqual([3, 2, 3])
    expect(getCoverArrangement(10)).toEqual([4, 2, 4])
    expect(getCoverArrangement(12)).toEqual([4, 4, 4])
    expect(getCoverArrangement(20)).toEqual([7, 6, 7])
  })

  it('accounts for every face exactly once and keeps the die in the middle row', () => {
    for (const die of PRODUCTION_DICE_SIDES) {
      const [top, middle, bottom] = getCoverArrangement(die)
      expect(top + middle + bottom, `d${die} faces`).toBe(die)
      // The die sits between the left and right halves of the middle row;
      // a d2/d4 with an empty middle row has its die between the outer rows.
      expect(Math.abs(top - bottom)).toBeLessThanOrEqual(1)
    }
  })

  it('trims partial pools without reordering faces or leaving empty rows', () => {
    expect(allocateCoverFaces(6, [2, 2, 2])).toEqual([2, 2, 2])
    expect(allocateCoverFaces(4, [2, 2, 2])).toEqual([2, 2, 0])
    expect(allocateCoverFaces(1, [0, 2, 0])).toEqual([0, 1, 0])
    expect(allocateCoverFaces(0, [3, 2, 3])).toEqual([0, 0, 0])
    for (const die of PRODUCTION_DICE_SIDES) {
      const arrangement = getCoverArrangement(die)
      for (let count = 0; count <= die; count++) {
        const rows = allocateCoverFaces(count, arrangement)
        expect(rows[0] + rows[1] + rows[2]).toBe(count)
      }
    }
  })

  it('falls back to d6 for unsupported or malformed die values', () => {
    expect(resolveProductionDie(3)).toBe(6)
    expect(resolveProductionDie(0)).toBe(6)
    expect(resolveProductionDie(Number.NaN)).toBe(6)
    expect(getCoverArrangement(3)).toEqual([2, 2, 2])
  })

  it('keeps covers proportional, centered and positive at every supported size', () => {
    for (const die of PRODUCTION_DICE_SIDES) {
      const layout = computeCoverBoardLayout({
        width: 1200,
        viewportHeight: 900,
        dieSize: die,
      })
      expect(layout.coverWidth, `d${die} cover width`).toBeGreaterThan(0)
      expect(layout.dieWidth, `d${die} die width`).toBeGreaterThanOrEqual(62)
      expect(layout.dieWidth, `d${die} die width ceiling`).toBeLessThanOrEqual(165)
      expect(layout.gap, `d${die} gap`).toBeGreaterThan(0)

      const [top, middle, bottom] = layout.arrangement
      const widestRow = Math.max(top, middle, bottom)
      const rowWidth = widestRow * layout.coverWidth + (widestRow - 1) * layout.gap
      const middleRowWidth = middle * layout.coverWidth + layout.dieWidth + layout.gap
      expect(rowWidth, `d${die} row fits`).toBeLessThanOrEqual(1200)
      expect(middleRowWidth, `d${die} middle row fits`).toBeLessThanOrEqual(1200)
    }
  })

  it('shrinks covers instead of forcing empty grid tracks when height is tight', () => {
    const roomy = computeCoverBoardLayout({ width: 1000, viewportHeight: 1200, dieSize: 20 })
    const tight = computeCoverBoardLayout({ width: 1000, viewportHeight: 500, dieSize: 20 })
    expect(tight.coverWidth).toBeLessThan(roomy.coverWidth)
    expect(tight.coverWidth).toBeGreaterThanOrEqual(34)
  })

  it('never emits negative geometry during a zero-width layout pass', () => {
    const layout = computeCoverBoardLayout({ width: 0, viewportHeight: 900, dieSize: 2 })
    expect(layout.coverWidth).toBeGreaterThanOrEqual(34)
    expect(Number.isFinite(layout.coverWidth)).toBe(true)
    expect(Number.isFinite(layout.dieWidth)).toBe(true)
  })

  it('uses a wider gap only on roomy boards', () => {
    expect(computeCoverBoardLayout({ width: 390, viewportHeight: 844, dieSize: 8 }).gap).toBe(8)
    expect(computeCoverBoardLayout({ width: 900, viewportHeight: 844, dieSize: 8 }).gap).toBe(13)
  })
})

describe('Night Shift mobile gallery geometry (#5981)', () => {
  it('wraps in both directions and handles empty pools', () => {
    expect(wrapCarouselIndex(-1, 8)).toBe(7)
    expect(wrapCarouselIndex(8, 8)).toBe(0)
    expect(wrapCarouselIndex(0, 0)).toBe(0)
  })

  it('keeps only the active cover and its immediate neighbors in view', () => {
    expect(carouselOffset(0, 0, 8)).toBe(0)
    expect(carouselOffset(1, 0, 8)).toBe(1)
    expect(carouselOffset(7, 0, 8)).toBe(-1)
    expect(carouselOffset(19, 0, 20)).toBe(-1)
    expect(carouselOffset(0, 19, 20)).toBe(1)
    for (let i = 0; i < 20; i++) {
      const offset = carouselOffset(i, 6, 20)
      expect(Math.abs(offset)).toBeLessThanOrEqual(10)
    }
  })

  it('centers the active cover at full scale and steps neighbors along the track', () => {
    expect(carouselTransform(0, 200)).toBe('translateX(calc(-50% + 0px)) scale(1)')
    expect(carouselTransform(1, 200)).toContain('scale(0.84)')
    expect(carouselTransform(1, 200)).toContain('194px')
  })

  it('sizes the dominant cover from available width with a legible clamp', () => {
    expect(galleryCoverWidth(390)).toBe(250)
    expect(galleryCoverWidth(320)).toBe(208)
    expect(galleryCoverWidth(160)).toBe(140)
    expect(GALLERY_SWIPE_THRESHOLD).toBe(35)
  })
})
