interface MarqueeTitleProps {
  title: string
  className?: string
}

export function MarqueeTitle({ title, className = '' }: MarqueeTitleProps) {
  return (
    <div className="min-w-0">
      <h3 className={`text-lg font-bold text-white whitespace-normal break-words ${className}`}>
        <span>{title}</span>
      </h3>
    </div>
  )
}
