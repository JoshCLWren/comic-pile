import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import './overlay.css'

interface OverlayPortalProps {
  children: React.ReactNode
}

const OVERLAY_ROOT_ID = 'comic-pile-overlay-root'
const OVERLAY_ROOT_CLASS = 'comic-pile-overlay-root'
let mountedPortalCount = 0

function getOrCreateOverlayRoot(): HTMLElement {
  const existingRoot = document.getElementById(OVERLAY_ROOT_ID)
  if (existingRoot) return existingRoot

  const overlayRoot = document.createElement('div')
  overlayRoot.id = OVERLAY_ROOT_ID
  overlayRoot.className = OVERLAY_ROOT_CLASS
  overlayRoot.dataset.overlayRoot = 'true'
  overlayRoot.dataset.overlayLayer = 'menu'
  document.body.appendChild(overlayRoot)
  return overlayRoot
}

export default function OverlayPortal({ children }: OverlayPortalProps) {
  const [overlayRoot, setOverlayRoot] = useState<HTMLElement | null>(null)

  useEffect(() => {
    const root = getOrCreateOverlayRoot()
    mountedPortalCount += 1
    setOverlayRoot(root)

    return () => {
      mountedPortalCount -= 1
      if (mountedPortalCount === 0) root.remove()
    }
  }, [])

  if (!overlayRoot) return null
  return createPortal(children, overlayRoot)
}
