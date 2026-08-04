import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

interface OverlayPortalProps {
  children: React.ReactNode
}

const OVERLAY_ROOT_ID = 'comic-pile-overlay-root'

function getOrCreateOverlayRoot(): HTMLElement {
  const existingRoot = document.getElementById(OVERLAY_ROOT_ID)
  if (existingRoot) return existingRoot

  const overlayRoot = document.createElement('div')
  overlayRoot.id = OVERLAY_ROOT_ID
  overlayRoot.dataset.overlayRoot = 'true'
  document.body.appendChild(overlayRoot)
  return overlayRoot
}

export default function OverlayPortal({ children }: OverlayPortalProps) {
  const [overlayRoot, setOverlayRoot] = useState<HTMLElement | null>(null)

  useEffect(() => {
    const root = getOrCreateOverlayRoot()
    setOverlayRoot(root)

    return () => {
      if (root.childElementCount === 0) root.remove()
    }
  }, [])

  if (!overlayRoot) return null
  return createPortal(children, overlayRoot)
}
