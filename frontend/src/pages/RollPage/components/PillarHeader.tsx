interface PillarHeaderProps {
  number: string
  title: string
  subtitle?: string
  accentColor?: string
}

export function PillarHeader({ number, title, subtitle, accentColor }: PillarHeaderProps) {
  return (
    <div className="flex items-center gap-2 border-b border-white/10 pb-2 mb-3">
      <span
        className="text-[10px] font-black tabular-nums opacity-60"
        style={{ color: accentColor }}
      >
        {number}
      </span>
      <h3
        className="text-[10px] font-black uppercase tracking-[0.18em]"
        style={{ color: accentColor }}
      >
        {title}
      </h3>
      {subtitle ? (
        <span className="text-[9px] font-bold uppercase tracking-wider text-stone-600 ml-auto">
          {subtitle}
        </span>
      ) : null}
    </div>
  )
}
