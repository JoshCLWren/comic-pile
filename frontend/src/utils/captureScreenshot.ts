import { toBlob } from 'html-to-image'

/**
 * Inject a <style> override that replaces CSS custom properties containing
 * oklch() values with their sRGB equivalents. html2canvas cannot parse oklch,
 * but the canvas 2D API always serialises fillStyle as sRGB — so we use that
 * as a cheap colour-conversion step before calling html2canvas.
 *
 * Returns the injected <style> element (caller must remove it) or null if no
 * oklch variables were found.
 */
function injectOklchFallbacks(): HTMLStyleElement | null {
  const tmp = document.createElement('canvas')
  tmp.width = 1
  tmp.height = 1
  const ctx = tmp.getContext('2d')
  if (!ctx) return null

  const overrides: Array<[string, string]> = []

  for (const sheet of Array.from(document.styleSheets)) {
    try {
      for (const rule of Array.from(sheet.cssRules)) {
        if (
          rule instanceof CSSStyleRule &&
          (rule.selectorText === ':root' ||
            rule.selectorText === ':root, :host' ||
            rule.selectorText === '*')
        ) {
          for (const prop of Array.from(rule.style)) {
            const val = rule.style.getPropertyValue(prop).trim()
            if (val.includes('oklch')) {
              ctx.fillStyle = val
              overrides.push([prop, ctx.fillStyle])
            }
          }
        }
      }
    } catch {
      // cross-origin stylesheet — skip
    }
  }

  if (overrides.length === 0) return null

  const style = document.createElement('style')
  style.setAttribute('data-screenshot-override', '1')
  style.textContent = `:root { ${overrides.map(([k, v]) => `${k}: ${v}`).join('; ')} }`
  document.head.appendChild(style)
  return style
}

/**
 * Capture the current page as a PNG Blob.
 *
 * Strategy:
 *  1. html-to-image toBlob  — fast, supports oklch, works on Chrome / Firefox.
 *  2. html2canvas fallback  — used when toBlob returns null or throws (Safari /
 *     iOS, where SVG foreignObject is blocked). oklch colours are normalised to
 *     sRGB before calling html2canvas.
 *
 * Returns null only if both approaches fail.
 */
export async function captureScreenshot(): Promise<Blob | null> {
  // ── Primary: html-to-image ──────────────────────────────────────────────────
  try {
    const blob = await toBlob(document.body, { skipFonts: true })
    if (blob !== null) return blob
  } catch {
    // fall through to html2canvas
  }

  // ── Fallback: html2canvas + oklch normalisation ────────────────────────────
  // Dynamically import so it doesn't bloat the main bundle on non-Safari browsers.
  let html2canvas: typeof import('html2canvas').default
  try {
    html2canvas = (await import('html2canvas')).default
  } catch {
    return null
  }

  const overrideStyle = injectOklchFallbacks()
  try {
    const canvas = await html2canvas(document.body, {
      useCORS: true,
      allowTaint: true,
      scale: Math.min(window.devicePixelRatio ?? 1, 2),
      logging: false,
    })
    return new Promise<Blob | null>(resolve => {
      canvas.toBlob(blob => resolve(blob), 'image/png')
    })
  } catch {
    return null
  } finally {
    if (overrideStyle) {
      document.head.removeChild(overrideStyle)
    }
  }
}
