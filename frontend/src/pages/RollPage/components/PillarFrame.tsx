import type { ReactNode } from 'react'

interface PillarFrameProps {
  number: string
  title: string
  accent: 'comic' | 'reading' | 'personal'
  subtitle?: string
  children: ReactNode
  className?: string
}

const accentVar: Record<PillarFrameProps['accent'], string> = {
  comic: 'var(--theme-comic-accent)',
  reading: 'var(--theme-continuity-accent)',
  personal: 'var(--theme-personal-accent)',
}

export function PillarFrame({
  number,
  title,
  accent,
  subtitle,
  children,
  className = '',
}: PillarFrameProps) {
  const accentColor = accentVar[accent]
  return (
    <aside
      className={`flex flex-col gap-3 rounded-2xl border border-[var(--theme-panel-border)] bg-[var(--theme-panel-bg)] p-4 ${className}`}
      style={{ borderLeftColor: accentColor }}
    >
      <div
        className="flex items-center gap-2"
        aria-label={`${number} ${title}`}
      >
        <span
          className="text-[10px] font-black uppercase tracking-[0.18em]"
          style={{ color: accentColor }}
          aria-hidden="true"
        >
          {number}
        </span>
        <span
          className="text-[10px] font-black uppercase tracking-[0.18em]"
          style={{ color: 'var(--theme-text-muted)' }}
        >
          {title}
        </span>
        <span
          className="ml-auto h-1 flex-1"
          style={{
            backgroundColor: accentColor,
            opacity: 0.4,
          }}
          aria-hidden="true"
        />
      </div>
      {subtitle ? (
        <p
          className="text-[9px] font-bold uppercase tracking-widest"
          style={{ color: 'var(--theme-text-muted)' }}
        >
          {subtitle}
        </p>
      ) : null}
      {children}
    </aside>
  )
}
