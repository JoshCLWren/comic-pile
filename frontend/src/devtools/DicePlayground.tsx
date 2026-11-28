import { useMemo, useState } from 'react'
import LazyDice3D from '../components/LazyDice3D'
import Tooltip from '../components/Tooltip'
import { DICE_LADDER } from '../components/diceLadder'
import {
  DEFAULT_DICE_RENDER_CONFIG,
  getDiceRenderConfigForSides,
} from '../components/diceRenderConfig'
import type {
  DiceRenderConfig,
  DiceRenderGlobalConfig,
  DiceRenderSideConfig,
  DiceSide,
} from '../components/diceTypes'

const STORAGE_KEY = 'comic-pile:dice-render-config'
const FONT_FAMILIES = [
  'Arial',
  'Helvetica',
  'Verdana',
  'Trebuchet MS',
  'Tahoma',
  'Georgia',
  'Times New Roman',
  'Courier New',
  'Monaco',
]
interface ControlHelpMap extends Record<string, string> {}

const CONTROL_HELP: ControlHelpMap = {
  'UV Inset': 'Shrinks UVs inward to reduce tile bleeding at face edges.',
  'Font Scale': 'Scales numeral size within each atlas tile.',
  'Text Offset X': 'Moves numbers left/right inside each tile.',
  'Text Offset Y': 'Moves numbers up/down inside each tile.',
  'Triangle UV Radius': 'Controls triangle face text footprint for d4/d8/d20.',
  'D12 UV Radius': 'Controls pentagon face text footprint for d12.',
  'D10 UV Padding': 'Adds inner padding for d10 quad mapping before sampling text.',
  'D10 Auto Center': 'Re-centers mapped d10 face bounds to tile center before offsets.',
  'D10 Top X (1-5)': 'Extra horizontal offset for d10 top-number group (1-5).',
  'D10 Top Y (1-5)': 'Extra vertical offset for d10 top-number group (1-5).',
  'D10 Bottom X (6-10)': 'Extra horizontal offset for d10 bottom-number group (6-10).',
  'D10 Bottom Y (6-10)': 'Extra vertical offset for d10 bottom-number group (6-10).',
  'Border Width': 'Atlas tile border thickness.',
  'Text Color': 'Numeral color in the texture atlas.',
  'Border Color': 'Tile border color in the texture atlas.',
  'Background Color': 'Tile background color in the texture atlas.',
  'Font Weight': 'Canvas font weight used when drawing numbers.',
  'Font Family': 'Canvas font family used when drawing numbers.',
}

function ControlLabel({ label }: { label: string }) {
  const help = CONTROL_HELP[label]
  return (
    <div className="flex items-center justify-between text-xs font-bold uppercase tracking-widest text-[var(--theme-text-primary)]">
      <span>{label}</span>
      {help && (
        <Tooltip content={help}>
          <button
            type="button"
            aria-label={`${label} help`}
            className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-[var(--theme-border)] text-[10px] text-[var(--theme-text-primary)] cursor-help"
          >
            ?
          </button>
        </Tooltip>
      )}
    </div>
  )
}

function buildValueList(sides: DiceSide): number[] {
  return Array.from({ length: sides }, (_, idx) => idx + 1)
}

function cloneConfig(config: DiceRenderConfig): DiceRenderConfig {
  // SAFETY: the JSON round-trip of a plain config object preserves its shape, so parse yields a DiceRenderConfig.
  return JSON.parse(JSON.stringify(config)) as DiceRenderConfig
}

function SliderControl({
  label,
  value,
  min,
  max,
  step,
  onChange,
  testId,
  onInteractionStart,
  onInteractionEnd,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
  testId: string
  onInteractionStart: () => void
  onInteractionEnd: () => void
}) {
  return (
    <label className="grid gap-2 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/70 p-3">
      <ControlLabel label={label} />
      <div className="text-right text-xs font-mono text-[var(--theme-text-muted)]">{Number(value).toFixed(3)}</div>
      <input
        data-testid={testId}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        onPointerDown={onInteractionStart}
        onPointerUp={onInteractionEnd}
        onPointerCancel={onInteractionEnd}
        onFocus={onInteractionStart}
        onBlur={onInteractionEnd}
      />
    </label>
  )
}

function ToggleControl({
  label,
  checked,
  onChange,
  testId,
  onInteractionStart,
  onInteractionEnd,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
  testId: string
  onInteractionStart: () => void
  onInteractionEnd: () => void
}) {
  return (
    <label className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/70 p-3">
      <div className="flex items-center justify-between">
        <ControlLabel label={label} />
      </div>
      <input
        data-testid={testId}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        onPointerDown={onInteractionStart}
        onPointerUp={onInteractionEnd}
        onPointerCancel={onInteractionEnd}
        onFocus={onInteractionStart}
        onBlur={onInteractionEnd}
        className="mt-2"
      />
    </label>
  )
}

function ColorControl({
  label,
  value,
  onChange,
  testId,
  onInteractionStart,
  onInteractionEnd,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  testId: string
  onInteractionStart: () => void
  onInteractionEnd: () => void
}) {
  return (
    <label className="grid gap-2 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/70 p-3">
      <ControlLabel label={label} />
      <div className="flex items-center gap-2">
        <input
          data-testid={testId}
          type="color"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onPointerDown={onInteractionStart}
          onPointerUp={onInteractionEnd}
          onPointerCancel={onInteractionEnd}
          onFocus={onInteractionStart}
          onBlur={onInteractionEnd}
          className="h-9 w-12 rounded border border-[var(--theme-border)] bg-transparent p-0"
        />
        <code className="text-xs text-[var(--theme-text-primary)]">{value}</code>
      </div>
    </label>
  )
}

function SelectControl({
  label,
  value,
  onChange,
  options,
  testId,
  onInteractionStart,
  onInteractionEnd,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: string[]
  testId: string
  onInteractionStart: () => void
  onInteractionEnd: () => void
}) {
  return (
    <label className="grid gap-2 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/70 p-3">
      <ControlLabel label={label} />
      <select
        data-testid={testId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onPointerDown={onInteractionStart}
        onPointerUp={onInteractionEnd}
        onPointerCancel={onInteractionEnd}
        onFocus={onInteractionStart}
        onBlur={onInteractionEnd}
        className="rounded border border-[var(--theme-border)] bg-[var(--theme-bg-page)] px-2 py-2 text-sm text-[var(--theme-text-primary)]"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  )
}

export default function DicePlayground() {
  const [sides, setSides] = useState<DiceSide>(20)
  const [value, setValue] = useState(1)
  const [isRolling, setIsRolling] = useState(false)
  const [freeze, setFreeze] = useState(true)
  const [renderConfig, setRenderConfig] = useState<DiceRenderConfig>(() => cloneConfig(DEFAULT_DICE_RENDER_CONFIG))
  const [jsonDraft, setJsonDraft] = useState(() => JSON.stringify(DEFAULT_DICE_RENDER_CONFIG, null, 2))
  const [statusMessage, setStatusMessage] = useState('')
  const [isTuning, setIsTuning] = useState(false)

  const values = useMemo(() => buildValueList(sides), [sides])
  const effectiveConfig = useMemo(
    () => getDiceRenderConfigForSides(sides, renderConfig),
    [sides, renderConfig],
  )

  function beginTuning() {
    setIsTuning(true)
  }

  function endTuning() {
    setIsTuning(false)
  }

  function syncDraft(nextConfig: DiceRenderConfig) {
    setRenderConfig(nextConfig)
    setJsonDraft(JSON.stringify(nextConfig, null, 2))
  }

  function handleSidesClick(nextSides: DiceSide) {
    setSides(nextSides)
    setValue(1)
  }

  function updateGlobal<K extends keyof DiceRenderGlobalConfig>(key: K, nextValue: DiceRenderGlobalConfig[K]) {
    const nextConfig = {
      ...renderConfig,
      global: {
        ...renderConfig.global,
        [key]: nextValue,
      },
    }
    syncDraft(nextConfig)
  }

  function updateSideOverride<K extends keyof DiceRenderSideConfig>(key: K, nextValue: DiceRenderSideConfig[K]) {
    const nextConfig = {
      ...renderConfig,
      perSides: {
        ...renderConfig.perSides,
        [sides]: {
          ...(renderConfig.perSides?.[sides] ?? {}),
          [key]: nextValue,
        },
      },
    }
    syncDraft(nextConfig)
  }

  function clearSideOverride() {
    const nextPerSides = { ...(renderConfig.perSides ?? {}) }
    delete nextPerSides[sides]
    const nextConfig = {
      ...renderConfig,
      perSides: nextPerSides,
    }
    syncDraft(nextConfig)
    setStatusMessage(`Cleared d${sides} override`)
  }

  async function copyPreset() {
    try {
      await navigator.clipboard.writeText(jsonDraft)
      setStatusMessage('Copied preset JSON to clipboard')
    } catch {
      setStatusMessage('Clipboard copy failed')
    }
  }

  function downloadPreset() {
    const blob = new Blob([jsonDraft], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `dice-render-config-d${sides}.json`
    link.click()
    URL.revokeObjectURL(url)
    setStatusMessage('Downloaded preset JSON')
  }

  function saveToLocalStorage() {
    localStorage.setItem(STORAGE_KEY, jsonDraft)
    setStatusMessage('Saved preset to localStorage')
  }

  function loadFromLocalStorage() {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) {
      setStatusMessage('No saved preset in localStorage')
      return
    }
    setJsonDraft(stored)
    tryApplyJson(stored)
  }

  function tryApplyJson(rawJson: string) {
    try {
      const parsed: Partial<DiceRenderConfig> = JSON.parse(rawJson)
      const merged = {
        ...cloneConfig(DEFAULT_DICE_RENDER_CONFIG),
        ...(parsed ?? {}),
        global: {
          ...cloneConfig(DEFAULT_DICE_RENDER_CONFIG).global,
          ...(parsed?.global ?? {}),
        },
        perSides: {
          ...(parsed?.perSides ?? {}),
        },
      }
      syncDraft(merged)
      setStatusMessage('Applied preset JSON')
    } catch {
      setStatusMessage('Invalid JSON preset')
    }
  }

  function applyDraftJson() {
    tryApplyJson(jsonDraft)
  }

  function resetDefaults() {
    const defaults = cloneConfig(DEFAULT_DICE_RENDER_CONFIG)
    syncDraft(defaults)
    setStatusMessage('Reset to defaults')
  }

  const sideOverride = renderConfig.perSides?.[sides] ?? {}

  return (
    <main className="min-h-screen px-4 py-8 text-[var(--theme-text-primary)]">
      <div className="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[420px_1fr] xl:items-start">
        <section className="space-y-4 rounded-2xl border border-[var(--theme-comic-accent)]/30 bg-[var(--theme-bg-page)]/60 p-4 xl:sticky xl:top-4">
          <header>
            <h1 className="text-2xl font-black tracking-wide">Dice Playground</h1>
            <p className="mt-2 text-sm text-[var(--theme-text-primary)]">
              Tune numeral rendering, placement, and UV mapping live.
            </p>
            <p className="mt-1 text-xs text-[var(--theme-text-muted)]">Entry: /dice-playground.html</p>
          </header>

          <div
            data-testid="dice-playground-canvas"
            className="mx-auto flex h-56 w-56 items-center justify-center rounded-full bg-[var(--theme-bg-page)]/80"
          >
            <LazyDice3D
              sides={sides}
              value={value}
              isRolling={isRolling}
              freeze={freeze}
              lockMotion={isTuning}
              color={0xffffff}
              renderConfig={renderConfig}
            />
          </div>

          <div className="text-center text-sm font-semibold text-[var(--theme-text-primary)]">
            Inspecting <span data-testid="dice-label">d{sides}</span> face{' '}
            <span data-testid="value-label">{value}</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              data-testid="toggle-roll"
              onClick={() => setIsRolling((prev) => !prev)}
              title="Starts/stops roll animation preview."
              className="rounded-lg border border-[var(--theme-continuity-accent)]/60 px-3 py-2 text-xs font-black uppercase tracking-widest text-[var(--theme-continuity-accent)] hover:bg-[var(--theme-continuity-accent)]/20"
            >
              {isRolling ? 'Stop Roll' : 'Start Roll'}
            </button>
            <button
              type="button"
              data-testid="toggle-freeze"
              onClick={() => setFreeze((prev) => !prev)}
              title="Freezes idle auto-spin when not rolling."
              className="rounded-lg border border-[var(--theme-personal-accent)]/60 px-3 py-2 text-xs font-black uppercase tracking-widest text-[var(--theme-personal-accent)] hover:bg-[var(--theme-personal-accent)]/20"
            >
              {freeze ? 'Unfreeze Idle Spin' : 'Freeze Idle Spin'}
            </button>
          </div>

          <p className="min-h-5 text-xs text-[var(--theme-comic-accent)]">{statusMessage}</p>
        </section>

        <section className="space-y-6 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto xl:pr-2">
          <section className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/60 p-4">
            <h2 className="text-xs font-black uppercase tracking-[0.2em] text-[var(--theme-comic-accent)]">Die size</h2>
            <div className="flex flex-wrap gap-2">
              {DICE_LADDER.map((die) => (
                <button
                  key={die}
                  type="button"
                  data-testid={`die-button-${die}`}
                  // SAFETY: DICE_LADDER contains exactly the valid DiceSide values, so each die id is a DiceSide.
                  onClick={() => handleSidesClick(die as DiceSide)}
                  className={`rounded-lg border px-3 py-2 text-sm font-black transition-colors ${
                    die === sides
                      ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-comic-accent)]/20 text-[var(--theme-comic-accent)]'
                      : 'border-[var(--theme-border)] bg-[var(--theme-bg-page)] text-[var(--theme-text-primary)] hover:border-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)]'
                  }`}
                >
                  d{die}
                </button>
              ))}
            </div>
          </section>

          <section className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/60 p-4">
            <h2 className="text-xs font-black uppercase tracking-[0.2em] text-[var(--theme-comic-accent)]">Face value</h2>
            <div className="flex max-h-48 flex-wrap gap-2 overflow-auto rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/50 p-3">
              {values.map((face) => (
                <button
                  key={face}
                  type="button"
                  data-testid={`value-button-${face}`}
                  onClick={() => setValue(face)}
                  className={`min-w-11 rounded-md border px-2 py-1 text-sm font-bold ${
                    face === value
                      ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-comic-accent)]/20 text-[var(--theme-comic-accent)]'
                      : 'border-[var(--theme-border)] text-[var(--theme-text-primary)] hover:border-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)]'
                  }`}
                >
                  {face}
                </button>
              ))}
            </div>
          </section>

          <section className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/60 p-4">
            <h2 className="text-xs font-black uppercase tracking-[0.2em] text-[var(--theme-comic-accent)]">Global tuning</h2>
            <div className="grid gap-3 md:grid-cols-2">
              <SliderControl label="UV Inset" value={renderConfig.global.uvInset} min={0} max={0.2} step={0.005} onChange={(next) => updateGlobal('uvInset', next)} testId="slider-global-uvInset" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Font Scale" value={renderConfig.global.fontScale} min={0.2} max={0.7} step={0.01} onChange={(next) => updateGlobal('fontScale', next)} testId="slider-global-fontScale" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Text Offset X" value={renderConfig.global.textOffsetX} min={-0.25} max={0.25} step={0.005} onChange={(next) => updateGlobal('textOffsetX', next)} testId="slider-global-textOffsetX" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Text Offset Y" value={renderConfig.global.textOffsetY} min={-0.25} max={0.25} step={0.005} onChange={(next) => updateGlobal('textOffsetY', next)} testId="slider-global-textOffsetY" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Triangle UV Radius" value={renderConfig.global.triangleUvRadius} min={0.2} max={0.49} step={0.005} onChange={(next) => updateGlobal('triangleUvRadius', next)} testId="slider-global-triangleUvRadius" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D12 UV Radius" value={renderConfig.global.d12UvRadius} min={0.2} max={0.49} step={0.005} onChange={(next) => updateGlobal('d12UvRadius', next)} testId="slider-global-d12UvRadius" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D10 UV Padding" value={renderConfig.global.d10UvPadding} min={0} max={0.2} step={0.005} onChange={(next) => updateGlobal('d10UvPadding', next)} testId="slider-global-d10UvPadding" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <ToggleControl label="D10 Auto Center" checked={!!renderConfig.global.d10AutoCenter} onChange={(next) => updateGlobal('d10AutoCenter', next)} testId="toggle-global-d10AutoCenter" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D10 Top X (1-5)" value={renderConfig.global.d10TopOffsetX ?? 0} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateGlobal('d10TopOffsetX', next)} testId="slider-global-d10TopOffsetX" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D10 Top Y (1-5)" value={renderConfig.global.d10TopOffsetY ?? 0} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateGlobal('d10TopOffsetY', next)} testId="slider-global-d10TopOffsetY" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D10 Bottom X (6-10)" value={renderConfig.global.d10BottomOffsetX ?? 0} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateGlobal('d10BottomOffsetX', next)} testId="slider-global-d10BottomOffsetX" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D10 Bottom Y (6-10)" value={renderConfig.global.d10BottomOffsetY ?? 0} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateGlobal('d10BottomOffsetY', next)} testId="slider-global-d10BottomOffsetY" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Border Width" value={renderConfig.global.borderWidth} min={0} max={12} step={0.5} onChange={(next) => updateGlobal('borderWidth', next)} testId="slider-global-borderWidth" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <ColorControl label="Text Color" value={renderConfig.global.textColor} onChange={(next) => updateGlobal('textColor', next)} testId="color-global-textColor" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <ColorControl label="Border Color" value={renderConfig.global.borderColor} onChange={(next) => updateGlobal('borderColor', next)} testId="color-global-borderColor" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <ColorControl label="Background Color" value={renderConfig.global.backgroundColor} onChange={(next) => updateGlobal('backgroundColor', next)} testId="color-global-backgroundColor" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SelectControl label="Font Weight" value={renderConfig.global.fontWeight} onChange={(next) => updateGlobal('fontWeight', next)} options={['normal', 'bold', 'bolder', 'lighter', '600', '700', '800']} testId="select-global-fontWeight" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SelectControl label="Font Family" value={renderConfig.global.fontFamily} onChange={(next) => updateGlobal('fontFamily', next)} options={FONT_FAMILIES} testId="select-global-fontFamily" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
            </div>
          </section>

          <section className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/60 p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-black uppercase tracking-[0.2em] text-[var(--theme-comic-accent)]">d{sides} override</h2>
              <button type="button" onClick={clearSideOverride} className="rounded-md border border-[var(--theme-error)]/60 px-2 py-1 text-xs font-bold text-[var(--theme-error)] hover:bg-[var(--theme-error)]/20">Clear d{sides}</button>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <SliderControl label="UV Inset" value={sideOverride.uvInset ?? effectiveConfig.uvInset} min={0} max={0.2} step={0.005} onChange={(next) => updateSideOverride('uvInset', next)} testId="slider-side-uvInset" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Font Scale" value={sideOverride.fontScale ?? effectiveConfig.fontScale} min={0.2} max={0.7} step={0.01} onChange={(next) => updateSideOverride('fontScale', next)} testId="slider-side-fontScale" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Text Offset X" value={sideOverride.textOffsetX ?? effectiveConfig.textOffsetX} min={-0.25} max={0.25} step={0.005} onChange={(next) => updateSideOverride('textOffsetX', next)} testId="slider-side-textOffsetX" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Text Offset Y" value={sideOverride.textOffsetY ?? effectiveConfig.textOffsetY} min={-0.25} max={0.25} step={0.005} onChange={(next) => updateSideOverride('textOffsetY', next)} testId="slider-side-textOffsetY" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="Triangle UV Radius" value={sideOverride.triangleUvRadius ?? effectiveConfig.triangleUvRadius} min={0.2} max={0.49} step={0.005} onChange={(next) => updateSideOverride('triangleUvRadius', next)} testId="slider-side-triangleUvRadius" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D12 UV Radius" value={sideOverride.d12UvRadius ?? effectiveConfig.d12UvRadius} min={0.2} max={0.49} step={0.005} onChange={(next) => updateSideOverride('d12UvRadius', next)} testId="slider-side-d12UvRadius" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              <SliderControl label="D10 UV Padding" value={sideOverride.d10UvPadding ?? effectiveConfig.d10UvPadding} min={0} max={0.2} step={0.005} onChange={(next) => updateSideOverride('d10UvPadding', next)} testId="slider-side-d10UvPadding" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
              {sides === 10 && (
                <>
                  <ToggleControl label="D10 Auto Center" checked={!!(sideOverride.d10AutoCenter ?? effectiveConfig.d10AutoCenter)} onChange={(next) => updateSideOverride('d10AutoCenter', next)} testId="toggle-side-d10AutoCenter" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
                  <SliderControl label="D10 Top X (1-5)" value={sideOverride.d10TopOffsetX ?? effectiveConfig.d10TopOffsetX} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateSideOverride('d10TopOffsetX', next)} testId="slider-side-d10TopOffsetX" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
                  <SliderControl label="D10 Top Y (1-5)" value={sideOverride.d10TopOffsetY ?? effectiveConfig.d10TopOffsetY} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateSideOverride('d10TopOffsetY', next)} testId="slider-side-d10TopOffsetY" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
                  <SliderControl label="D10 Bottom X (6-10)" value={sideOverride.d10BottomOffsetX ?? effectiveConfig.d10BottomOffsetX} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateSideOverride('d10BottomOffsetX', next)} testId="slider-side-d10BottomOffsetX" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
                  <SliderControl label="D10 Bottom Y (6-10)" value={sideOverride.d10BottomOffsetY ?? effectiveConfig.d10BottomOffsetY} min={-0.2} max={0.2} step={0.002} onChange={(next) => updateSideOverride('d10BottomOffsetY', next)} testId="slider-side-d10BottomOffsetY" onInteractionStart={beginTuning} onInteractionEnd={endTuning} />
                </>
              )}
            </div>
          </section>

          <section className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/60 p-4">
            <h2 className="text-xs font-black uppercase tracking-[0.2em] text-[var(--theme-comic-accent)]">Preset JSON</h2>
            <div className="grid gap-2 md:grid-cols-3">
              <button type="button" title="Parses current JSON draft and applies it to live renderer." data-testid="btn-apply-json" onClick={applyDraftJson} className="rounded-md border border-[var(--theme-comic-accent)]/60 px-2 py-2 text-xs font-bold text-[var(--theme-comic-accent)] hover:bg-[var(--theme-comic-accent)]/20">Apply JSON</button>
              <button type="button" title="Saves current JSON draft into browser localStorage for this origin." onClick={saveToLocalStorage} className="rounded-md border border-[var(--theme-personal-accent)]/60 px-2 py-2 text-xs font-bold text-[var(--theme-personal-accent)] hover:bg-[var(--theme-personal-accent)]/20">Save Local</button>
              <button type="button" title="Loads saved JSON draft from browser localStorage and applies it." onClick={loadFromLocalStorage} className="rounded-md border border-[var(--theme-personal-accent)]/60 px-2 py-2 text-xs font-bold text-[var(--theme-personal-accent)] hover:bg-[var(--theme-personal-accent)]/20">Load Local</button>
              <button type="button" title="Copies current JSON draft to clipboard." onClick={copyPreset} className="rounded-md border border-[var(--theme-continuity-accent)]/60 px-2 py-2 text-xs font-bold text-[var(--theme-continuity-accent)] hover:bg-[var(--theme-continuity-accent)]/20">Copy JSON</button>
              <button type="button" title="Downloads current JSON draft as a preset file." onClick={downloadPreset} className="rounded-md border border-[var(--theme-continuity-accent)]/60 px-2 py-2 text-xs font-bold text-[var(--theme-continuity-accent)] hover:bg-[var(--theme-continuity-accent)]/20">Download JSON</button>
              <button type="button" title="Resets live config back to committed defaults." onClick={resetDefaults} className="rounded-md border border-[var(--theme-error)]/60 px-2 py-2 text-xs font-bold text-[var(--theme-error)] hover:bg-[var(--theme-error)]/20">Reset Defaults</button>
            </div>
            <textarea
              data-testid="preset-json"
              value={jsonDraft}
              onChange={(event) => setJsonDraft(event.target.value)}
              onFocus={beginTuning}
              onBlur={endTuning}
              className="min-h-60 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)] p-3 font-mono text-xs text-[var(--theme-text-primary)]"
            />
          </section>
        </section>
      </div>
    </main>
  )
}
