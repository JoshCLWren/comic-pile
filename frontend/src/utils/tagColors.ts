/**
 * The fixed tag color palette, mirrored from `app/constants.py:TAG_COLOR_PALETTE`.
 *
 * The server validates every tag color against this palette and returns the hex
 * value, so the frontend keeps a name -> hex map only for rendering names and
 * for the color picker's swatch grid. The server remains authoritative: an
 * unknown color is rendered as-is rather than silently remapped.
 */
export const TAG_COLOR_PALETTE: Record<string, string> = {
  red: '#DC2626',
  orange: '#F97316',
  amber: '#F59E0B',
  yellow: '#EAB308',
  lime: '#84CC16',
  green: '#22C55E',
  emerald: '#10B981',
  teal: '#14B8A6',
  cyan: '#06B6D4',
  sky: '#0EA5E9',
  blue: '#3B82F6',
  indigo: '#6366F1',
  violet: '#8B5CF6',
  purple: '#A855F7',
  fuchsia: '#D946EF',
  pink: '#EC4899',
  rose: '#F43F5E',
  crimson: '#B91C1C',
  burgundy: '#7F1D1D',
  maroon: '#78350F',
  brown: '#92400E',
  gold: '#D97706',
  bronze: '#B45309',
  khaki: '#A16207',
  olive: '#65A30D',
  forest: '#15803D',
  mint: '#34D399',
  ice: '#22D3EE',
  cobalt: '#2563EB',
  royal: '#4F46E5',
  'violet-deep': '#7C3AED',
  magenta: '#E879F9',
}

/** Palette names in display order, matching the server's declaration order. */
export const TAG_COLOR_NAMES: readonly string[] = Object.keys(TAG_COLOR_PALETTE)

/** The palette entry new tags default to. */
export const DEFAULT_TAG_COLOR_NAME = 'red'

/**
 * Resolve a tag's stored color to a renderable hex value.
 *
 * @param color - A palette name or a `#RRGGBB` value from the API.
 * @returns The hex value to render.
 */
export function resolveTagColorHex(color: string): string {
  return TAG_COLOR_PALETTE[color] ?? color
}

/**
 * Resolve a tag's stored color back to its palette name.
 *
 * @param color - A palette name or a `#RRGGBB` value from the API.
 * @returns The matching palette name, or the original value when it is unknown.
 */
export function resolveTagColorName(color: string): string {
  const match = TAG_COLOR_NAMES.find((name) => TAG_COLOR_PALETTE[name] === color)
  return match ?? color
}