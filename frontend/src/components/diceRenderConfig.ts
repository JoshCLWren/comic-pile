export interface GlobalConfig {
  tileSize: number
  uvInset: number
  fontScale: number
  textOffsetX: number
  textOffsetY: number
  borderWidth: number
  triangleUvRadius: number
  d12UvRadius: number
  d10UvPadding: number
  d10AutoCenter: boolean
  d10TopOffsetX: number
  d10TopOffsetY: number
  d10BottomOffsetX: number
  d10BottomOffsetY: number
  textColor: string
  borderColor: string
  backgroundColor: string
  fontFamily: string
  fontWeight: string
}

export type SideConfig = Partial<GlobalConfig>

export interface DiceRenderConfig {
  global: GlobalConfig
  perSides: Record<string | number, SideConfig>
}

const DEFAULT_GLOBAL_CONFIG: GlobalConfig = {
  tileSize: 256,
  uvInset: 0.045,
  fontScale: 0.36,
  textOffsetX: -0.005,
  textOffsetY: 0.135,
  borderWidth: 6,
  triangleUvRadius: 0.41,
  d12UvRadius: 0.42,
  d10UvPadding: 0,
  d10AutoCenter: false,
  d10TopOffsetX: 0,
  d10TopOffsetY: 0,
  d10BottomOffsetX: 0,
  d10BottomOffsetY: 0,
  textColor: '#1a1a2e',
  borderColor: '#cccccc',
  backgroundColor: '#ffffff',
  fontFamily: 'Arial',
  fontWeight: 'bold',
}

export const DEFAULT_DICE_RENDER_CONFIG: DiceRenderConfig = {
  global: DEFAULT_GLOBAL_CONFIG,
  perSides: {
    6: {
      textOffsetY: 0.04,
      fontScale: 0.58,
    },
    10: {
      uvInset: 0.1,
      fontScale: 0.35,
      textOffsetX: -0.07,
      textOffsetY: 0.09,
      triangleUvRadius: 0.49,
      d10UvPadding: 0.06,
    },
    12: {
      textOffsetY: 0.03,
    },
  },
}

function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return fallback
  }
  return Math.max(min, Math.min(max, numeric))
}

function clampInteger(value: unknown, fallback: number, min: number, max: number): number {
  return Math.round(clampNumber(value, fallback, min, max))
}

function pickString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback
}

function pickBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

export function getDiceRenderConfigForSides(
  sides: number,
  overrides: Partial<DiceRenderConfig> | null = null
): GlobalConfig {
  const defaultGlobal = DEFAULT_DICE_RENDER_CONFIG.global ?? {}
  const defaultSide =
    DEFAULT_DICE_RENDER_CONFIG.perSides?.[String(sides)] ??
    DEFAULT_DICE_RENDER_CONFIG.perSides?.[sides] ??
    {}
  const globalOverrides = overrides?.global ?? {}
  const sideOverrides = overrides?.perSides?.[String(sides)] ?? overrides?.perSides?.[sides] ?? {}

  const raw: Record<string, unknown> = {
    ...DEFAULT_GLOBAL_CONFIG,
    ...defaultGlobal,
    ...defaultSide,
    ...globalOverrides,
    ...sideOverrides,
  }

  return {
    tileSize: clampInteger(raw.tileSize, DEFAULT_GLOBAL_CONFIG.tileSize, 64, 1024),
    uvInset: clampNumber(raw.uvInset, DEFAULT_GLOBAL_CONFIG.uvInset, 0, 0.25),
    fontScale: clampNumber(raw.fontScale, DEFAULT_GLOBAL_CONFIG.fontScale, 0.1, 0.8),
    textOffsetX: clampNumber(raw.textOffsetX, DEFAULT_GLOBAL_CONFIG.textOffsetX, -0.4, 0.4),
    textOffsetY: clampNumber(raw.textOffsetY, DEFAULT_GLOBAL_CONFIG.textOffsetY, -0.4, 0.4),
    borderWidth: clampInteger(raw.borderWidth, DEFAULT_GLOBAL_CONFIG.borderWidth, 0, 20),
    triangleUvRadius: clampNumber(
      raw.triangleUvRadius,
      DEFAULT_GLOBAL_CONFIG.triangleUvRadius,
      0.15,
      0.49,
    ),
    d12UvRadius: clampNumber(raw.d12UvRadius, DEFAULT_GLOBAL_CONFIG.d12UvRadius, 0.15, 0.49),
    d10UvPadding: clampNumber(raw.d10UvPadding, DEFAULT_GLOBAL_CONFIG.d10UvPadding, 0, 0.25),
    d10AutoCenter: pickBoolean(raw.d10AutoCenter, DEFAULT_GLOBAL_CONFIG.d10AutoCenter),
    d10TopOffsetX: clampNumber(raw.d10TopOffsetX, DEFAULT_GLOBAL_CONFIG.d10TopOffsetX, -0.5, 0.5),
    d10TopOffsetY: clampNumber(raw.d10TopOffsetY, DEFAULT_GLOBAL_CONFIG.d10TopOffsetY, -0.5, 0.5),
    d10BottomOffsetX: clampNumber(
      raw.d10BottomOffsetX,
      DEFAULT_GLOBAL_CONFIG.d10BottomOffsetX,
      -0.5,
      0.5,
    ),
    d10BottomOffsetY: clampNumber(
      raw.d10BottomOffsetY,
      DEFAULT_GLOBAL_CONFIG.d10BottomOffsetY,
      -0.5,
      0.5,
    ),
    textColor: pickString(raw.textColor, DEFAULT_GLOBAL_CONFIG.textColor),
    borderColor: pickString(raw.borderColor, DEFAULT_GLOBAL_CONFIG.borderColor),
    backgroundColor: pickString(raw.backgroundColor, DEFAULT_GLOBAL_CONFIG.backgroundColor),
    fontFamily: pickString(raw.fontFamily, DEFAULT_GLOBAL_CONFIG.fontFamily),
    fontWeight: pickString(raw.fontWeight, DEFAULT_GLOBAL_CONFIG.fontWeight),
  }
}
