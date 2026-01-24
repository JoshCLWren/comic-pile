/**
 * A reusable modal dialog component with backdrop blur effect.
 *
 * @param {Object} props - Component props
 * @param {boolean} props.isOpen - Whether the modal is currently visible
 * @param {string} props.title - The modal title displayed in the header
 * @param {Function} props.onClose - Callback function when the modal is closed
 * @param {React.ReactNode} props.children - The content to render inside the modal
 * @returns {JSX.Element|null} The modal component or null if not open
 */
export default function Modal({ isOpen, title, onClose, children }) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-slate-900/70 backdrop-blur" onClick={onClose} aria-hidden="true"></div>
      <div className="relative w-full max-w-lg glass-card p-6 space-y-6">
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
