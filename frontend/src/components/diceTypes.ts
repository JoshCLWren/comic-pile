export type DiceSide = 4 | 6 | 8 | 10 | 12 | 20

export function isDiceSide(value: number): value is DiceSide {
  return value === 4 || value === 6 || value === 8 || value === 10 || value === 12 || value === 20
}

export interface DiceRenderGlobalConfig {
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

export type DiceRenderSideConfig = Partial<DiceRenderGlobalConfig>

export interface DiceRenderConfig {
  global: DiceRenderGlobalConfig
  perSides: Partial<Record<number, DiceRenderSideConfig>>
}

export interface Dice3DProps {
  sides?: DiceSide
  value?: number
  isRolling?: boolean
  freeze?: boolean
  lockMotion?: boolean
  color?: number
  onRollComplete?: (() => void) | null
  renderConfig?: Partial<DiceRenderConfig> | null
  showValue?: boolean
}
