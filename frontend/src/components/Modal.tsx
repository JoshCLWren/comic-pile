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
    <div data-exclude-from-screenshot="true" className={`fixed inset-0 z-50 flex items-center justify-center px-4 ${overlayClassName || ''}`}>
      <div className="absolute inset-0 bg-[#110e0a]/80" onClick={onClose} aria-hidden="true"></div>
      <div
        ref={modalRef}
        data-testid={testId}
        className="relative w-full max-w-lg glass-card p-6 max-h-[85vh] flex flex-col"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="flex items-start justify-between gap-4 pb-4 shrink-0">
          <h2 id="modal-title" className="text-xl font-black tracking-tight text-stone-200 uppercase">{title}</h2>
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
