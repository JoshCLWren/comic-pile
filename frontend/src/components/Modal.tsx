import { useEffect, useRef } from 'react'

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
  const modalRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const onCloseRef = useRef(onClose)

  // Keep onCloseRef up to date without causing effect re-runs
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!isOpen) return

    previousFocusRef.current = document.activeElement as HTMLElement

    const modal = modalRef.current
    if (!modal) return

    const focusableElements = modal.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCloseRef.current()
        return
      }

      if (e.key === 'Tab' && focusableElements.length > 0) {
        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault()
            lastElement?.focus()
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault()
            firstElement?.focus()
          }
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    // Focus the first input/textarea/select element, or fall back to the first focusable element
    const focusableArray = Array.from(focusableElements)
    const firstInput = focusableArray.find(
      el => el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT'
    )
    const targetElement = firstInput || firstElement
    targetElement?.focus()

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previousFocusRef.current?.focus()
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div data-exclude-from-screenshot="true" className={`fixed inset-0 z-[60] flex items-end md:items-center justify-center md:px-4 ${overlayClassName || ''}`}>
      <div className="absolute inset-0 bg-[#110e0a]/60 backdrop-blur-sm" onClick={onClose} aria-hidden="true"></div>
      <div
        ref={modalRef}
        data-testid={testId}
        className="relative w-full max-w-lg modal-card max-h-[90vh] md:max-h-[85vh] flex flex-col rounded-t-2xl md:rounded-lg animate-slide-up md:animate-fade-in pb-[env(safe-area-inset-bottom)]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="flex justify-center pt-2 pb-1 md:hidden shrink-0">
          <div className="w-10 h-1 bg-white/20 rounded-full" />
        </div>
        <div className="flex items-start justify-between gap-2 md:gap-4 px-4 md:px-6 pt-2 md:pt-0 pb-3 md:pb-4 shrink-0">
          <h2 id="modal-title" className="text-lg md:text-xl font-black tracking-tight text-stone-200 uppercase">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-stone-500 hover:text-stone-300 transition-colors text-2xl leading-none"
            aria-label="Close modal"
          >
            &times;
          </button>
        </div>
        <div className="overflow-y-auto space-y-4 md:space-y-6 min-h-0 px-4 md:px-6 pb-4 md:pb-6">
          {children}
        </div>
      </div>
    </div>
  )
}
