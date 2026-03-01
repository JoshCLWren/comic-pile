import { useEffect } from 'react'

export default function Modal({ isOpen, title, onClose, children, 'data-testid': testId, overlayClassName }) {
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e) => {
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
      <div className="absolute inset-0 bg-slate-900/70 backdrop-blur" onClick={onClose} aria-hidden="true"></div>
      <div data-testid={testId} className="relative w-full max-w-lg glass-card p-6 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-xl font-black tracking-tight text-slate-100 uppercase">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-500 hover:text-slate-200 transition-colors text-2xl leading-none"
            aria-label="Close modal"
          >
            &times;
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
