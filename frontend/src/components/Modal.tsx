import { useEffect } from 'react'

interface ModalProps {
  isOpen: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
  'data-testid'?: string
  overlayClassName?: string
}

export default function Modal({
  isOpen,
  title,
  onClose,
  children,
  'data-testid': testId,
  overlayClassName,
}: ModalProps) {
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center px-4 ${overlayClassName || ''}`}>
      <div className="absolute inset-0 bg-[#110e0a]/80" onClick={onClose} aria-hidden="true"></div>
      <div data-testid={testId} className="relative w-full max-w-lg glass-card p-6 max-h-[85vh] flex flex-col">
        <div className="flex items-start justify-between gap-4 pb-4 shrink-0">
          <h2 className="text-xl font-black tracking-tight text-stone-200 uppercase">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-stone-500 hover:text-stone-300 transition-colors text-2xl leading-none"
            aria-label="Close modal"
          >
            &times;
          </button>
        </div>
        <div className="overflow-y-auto space-y-6 min-h-0">
          {children}
        </div>
      </div>
    </div>
  )
}
