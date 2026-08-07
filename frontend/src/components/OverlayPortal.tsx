import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import './overlay.css'

export type OverlayLayer = 'menu' | 'dialog' | 'global-effect'

interface OverlayPortalProps {
  children: React.ReactNode
  layer?: OverlayLayer
}

const OVERLAY_ROOT_ID = 'comic-pile-overlay-root'
const mountedPortalCounts = new Map<OverlayLayer, number>()

function getOverlayRootId(layer: OverlayLayer): string {
  return layer === 'menu' ? OVERLAY_ROOT_ID : `${OVERLAY_ROOT_ID}-${layer}`
}

function getOrCreateOverlayRoot(layer: OverlayLayer): HTMLElement {
  const rootId = getOverlayRootId(layer)
  const existingRoot = document.getElementById(rootId)
  if (existingRoot) return existingRoot

  const overlayRoot = document.createElement('div')
  overlayRoot.id = rootId
  overlayRoot.className = `comic-pile-overlay-root comic-pile-overlay-root--${layer}`
  overlayRoot.dataset.overlayRoot = 'true'
  overlayRoot.dataset.overlayLayer = layer
  document.body.appendChild(overlayRoot)
  return overlayRoot
}

export default function OverlayPortal({ children, layer = 'menu' }: OverlayPortalProps) {
  const [overlayRoot, setOverlayRoot] = useState<HTMLElement | null>(null)

  useEffect(() => {
    const root = getOrCreateOverlayRoot(layer)
    mountedPortalCounts.set(layer, (mountedPortalCounts.get(layer) ?? 0) + 1)
    setOverlayRoot(root)

    return () => {
      const remaining = mountedPortalCounts.get(layer)! - 1
      if (remaining <= 0) {
        mountedPortalCounts.delete(layer)
        root.remove()
      } else {
        mountedPortalCounts.set(layer, remaining)
      }
    }
  }, [layer])

  if (!overlayRoot) return null
  return createPortal(children, overlayRoot)
}
