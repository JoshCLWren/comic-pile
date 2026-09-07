import { FORMAT_OPTIONS } from './types'

export function FormatSelect({ value, onChange, required, id }: {
  value: string
  onChange: (value: string) => void
  required?: boolean
  id?: string
}) {
  const hasCustom = value && !FORMAT_OPTIONS.includes(value as typeof FORMAT_OPTIONS[number])

  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-xl px-3 py-2 text-sm form-control"
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
