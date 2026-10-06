import React from 'react'

interface ComicVineMappingStatusProps {
  isMapped: boolean
}

export function ComicVineMappingStatus({ isMapped }: ComicVineMappingStatusProps) {
  if (!isMapped) {
    return null
  }

  return (
    <span
      className="inline-flex min-h-5 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider border-[var(--theme-comic-accent)]/30 text-[var(--theme-comic-accent)]"
    >
      <span
        aria-hidden="true"
        className="w-1.5 h-1.5 rounded-full bg-[var(--theme-comic-accent)]"
      />
      Linked
    </span>
  )
}