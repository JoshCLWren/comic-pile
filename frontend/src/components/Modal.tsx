import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import OverlayPortal from './OverlayPortal'

interface ModalProps {
  isOpen: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
  'data-testid'?: string
  overlayClassName?: string
  autoFocus?: boolean
}

// Module-level lock counter so nested/overlapping modals don't prematurely
// unlock #root scroll. The lock is only released when the last modal closes.
let rootLockCount = 0
let savedOverflow = ''
let savedScrollTop = 0

// Module-level stack so overlapping modals know which one is on top. Each open
// also receives a higher visual layer, keeping Escape/backdrop ownership aligned
// with the modal the browser actually paints above the others.
const openModalStack: number[] = []
let nextModalId = 0
let nextModalLayer = 60

function isTopmostModal(modalId: number): boolean {
  return openModalStack[openModalStack.length - 1] === modalId
}

export default function Modal({
  isOpen,
  title,
  onClose,
  children,
  'data-testid': testId,
  overlayClassName,
  autoFocus = true,
}: ModalProps) {
  const [overlayElement, setOverlayElement] = useState<HTMLDivElement | null>(null)
  const modalRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const onCloseRef = useRef(onClose)
  const titleId = useId()

  const modalIdRef = useRef<number | null>(null)
  if (modalIdRef.current === null) {
    modalIdRef.current = nextModalId++
  }

  // Keep onCloseRef up to date without causing effect re-runs
  useEffect(() => {
    onCloseRef.current = onClose
  })

  // OverlayPortal creates its shared root after the parent modal's first commit.
  // Wait until the portaled overlay node is attached before registering, layering,
  // or focusing the modal. This avoids dereferencing a ref that cannot exist yet.
  useLayoutEffect(() => {
    if (!isOpen || !overlayElement || !modalRef.current) return

    const modalId = modalIdRef.current!
    // This effect's cleanup always removes its entry before a rerun, so every
    // active modal has exactly one stack entry.
    openModalStack.push(modalId)
    overlayElement.style.zIndex = String(nextModalLayer++)

    previousFocusRef.current = document.activeElement as HTMLElement

    const modal = modalRef.current

    const focusableElements = modal.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    const firstElement = focusableElements[0]
    const lastElement = focusableElements[focusableElements.length - 1]

    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isTopmostModal(modalId)) return

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
        } else if (document.activeElement === lastElement) {
          e.preventDefault()
          firstElement?.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    // Focus the first input/textarea/select element, or fall back to the first focusable element
    const focusableArray = Array.from(focusableElements)
    const firstInput = focusableArray.find(
      el => el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT'
    )
    const targetElement = autoFocus
      ? firstInput || firstElement
      : closeButtonRef.current
    targetElement?.focus()

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      const cleanupIndex = openModalStack.indexOf(modalId)
      const wasTopmost = cleanupIndex === openModalStack.length - 1
      // An open modal always owns one stack entry until this cleanup executes.
      openModalStack.splice(cleanupIndex, 1)
      if (openModalStack.length === 0) nextModalLayer = 60

      // Only restore focus when this modal was the topmost layer. Closing a
      // lower modal must not steal focus from the modal rendered above it.
      if (wasTopmost) {
        previousFocusRef.current?.focus()
      }
    }
  }, [autoFocus, isOpen, overlayElement])

  // Lock the #root scroller while a modal is open (fixes iOS scroll-bleed).
  // The dialog itself is portaled to document.body, so locking #root no longer
  // affects touch-panning inside modal content. The ref count still protects
  // nested and overlapping dialogs from prematurely restoring page scrolling.
  useEffect(() => {
    if (!isOpen) return
    const root = document.getElementById('root')
    if (!root) return
    if (rootLockCount === 0) {
      savedOverflow = root.style.overflow
      savedScrollTop = root.scrollTop
      root.style.overflow = 'hidden'
    }
    rootLockCount++
    return () => {
      rootLockCount--
      if (rootLockCount === 0) {
        root.style.overflow = savedOverflow
        root.scrollTop = savedScrollTop
      }
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <OverlayPortal layer="dialog">
      <div
        ref={setOverlayElement}
        className={`fixed inset-0 flex items-end md:items-center justify-center md:px-4 ${overlayClassName || ''}`}
        style={{ zIndex: 60 }}
      >
        <div
          className="absolute inset-0 bg-[#110e0a]/60 backdrop-blur-sm touch-none"
          onClick={() => {
            if (isTopmostModal(modalIdRef.current!)) onClose()
          }}
          aria-hidden="true"
        ></div>
        <div
          ref={modalRef}
          data-testid={testId}
          tabIndex={-1}
          className="relative w-full max-w-lg h-[calc(100dvh-1rem)] md:h-auto modal-card max-h-[calc(100dvh-1rem)] md:max-h-[85vh] flex flex-col overflow-hidden rounded-t-2xl md:rounded-lg animate-slide-up md:animate-fade-in pb-[env(safe-area-inset-bottom)]"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
        >
          <div className="flex justify-center pt-2 pb-1 md:hidden shrink-0">
            <div className="w-10 h-1 bg-white/20 rounded-full" />
          </div>
          <div className="flex items-start justify-between gap-2 md:gap-4 px-4 md:px-6 pt-2 md:pt-0 pb-3 md:pb-4 shrink-0">
            <h2 id={titleId} className="min-w-0 flex-1 text-base md:text-xl font-black tracking-tight text-stone-200 uppercase">{title}</h2>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              className="text-stone-500 hover:text-stone-300 transition-colors text-2xl leading-none"
              aria-label="Close modal"
            >
              &times;
            </button>
          </div>
          <div className="overflow-y-auto space-y-4 md:space-y-6 min-h-0 px-4 md:px-6 pb-4 md:pb-6 overscroll-contain">
            {children}
          </div>
        </div>
      </div>
    </OverlayPortal>
  )
}
