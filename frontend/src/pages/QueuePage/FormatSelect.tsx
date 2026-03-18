import { FORMAT_OPTIONS } from './types'

export function FormatSelect({ value, onChange, required }: {
  value: string
  onChange: (value: string) => void
  required?: boolean
}) {
  const hasCustom = value && !FORMAT_OPTIONS.includes(value as typeof FORMAT_OPTIONS[number])

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
      required={required}
    >
      <option value="">Select format...</option>
      {hasCustom && <option value={value}>{value}</option>}
      {FORMAT_OPTIONS.map((fmt) => (
        <option key={fmt} value={fmt}>{fmt}</option>
      ))}
    </select>
  )
}
