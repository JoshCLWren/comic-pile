import { toBlob } from 'html-to-image'

/**
 * Probe whether this browser can render SVG <foreignObject> content.
 *
 * Renders a 16×16 green div via foreignObject to a canvas and samples the
 * centre pixel. Returns true only when the pixel is actually green — meaning
 * foreignObject rendering works correctly on this device right now.
 *
 * This is the same technique used internally by html2canvas. UA sniffing is
 * intentionally avoided: Safari behaviour varies across iOS versions,
 * WKWebView vs Safari, and DOM/CSS complexity.
 */
async function supportsForeignObjectRendering(): Promise<boolean> {
  try {
    const size = 16
    const xmlns = 'http://www.w3.org/2000/svg'

    const svg = document.createElementNS(xmlns, 'svg')
    svg.setAttribute('width', String(size))
    svg.setAttribute('height', String(size))
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`)

    const foreignObject = document.createElementNS(xmlns, 'foreignObject')
    foreignObject.setAttribute('x', '0')
    foreignObject.setAttribute('y', '0')
    foreignObject.setAttribute('width', '100%')
    foreignObject.setAttribute('height', '100%')

    const div = document.createElement('div')
    div.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml')
    div.style.width = `${size}px`
    div.style.height = `${size}px`
    div.style.background = 'rgb(0, 255, 0)'

    foreignObject.appendChild(div)
    svg.appendChild(foreignObject)

    const serialized = new XMLSerializer().serializeToString(svg)
    const dataUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(serialized)

    const img = new Image()
    img.decoding = 'sync'

    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new Error('foreignObject probe image load failed'))
      img.src = dataUrl
    })

    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d')
    if (!ctx) return false

    ctx.drawImage(img, 0, 0)

    const [r, g, b, a] = ctx.getImageData(8, 8, 1, 1).data
    return r < 10 && g > 245 && b < 10 && a > 245
  } catch {
    return false
  }
}

let foreignObjectSupportPromise: Promise<boolean> | null = null

/** Returns cached foreignObject support for this page session. */
function getForeignObjectSupport(): Promise<boolean> {
  if (!foreignObjectSupportPromise) {
    foreignObjectSupportPromise = supportsForeignObjectRendering()
  }
  return foreignObjectSupportPromise
}

/**
 * Returns true if the blob appears to be blank, black, or nearly uniform —
 * indicating a failed/silent render rather than real content.
 *
 * Downsamples to sampleSize×sampleSize before pixel inspection so it runs
 * quickly regardless of the blob's original dimensions.
 */
async function blobLooksBlankOrBlack(
  blob: Blob,
  { sampleSize = 8, uniformTolerance = 8 }: { sampleSize?: number; uniformTolerance?: number } = {}
): Promise<boolean> {
  try {
    const bitmap = await createImageBitmap(blob)

    const canvas = document.createElement('canvas')
    canvas.width = sampleSize
    canvas.height = sampleSize

    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return true

    ctx.drawImage(bitmap, 0, 0, sampleSize, sampleSize)
    const data = ctx.getImageData(0, 0, sampleSize, sampleSize).data

    let blackish = 0
    let transparentish = 0
    let min = 255
    let max = 0

    for (let i = 0; i < data.length; i += 4) {
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      const a = data[i + 3]
      const luminance = (r + g + b) / 3

      if (a < 10) transparentish++
      if (a > 245 && luminance < 10) blackish++

      min = Math.min(min, r, g, b, a)
      max = Math.max(max, r, g, b, a)
    }

    const total = data.length / 4
    const almostAllBlack = blackish / total > 0.98
    const almostAllTransparent = transparentish / total > 0.98
    const nearlyUniform = max - min <= uniformTolerance

    return almostAllBlack || almostAllTransparent || nearlyUniform
  } catch {
    return true
  }
}

/**
 * Walk all CSS rules recursively, yielding every CSSRule including those
 * nested inside @layer, @media, @supports, etc.
 */
function* iterateCSSRules(rules: CSSRuleList): Generator<CSSRule> {
  for (const rule of Array.from(rules)) {
    yield rule
    if ('cssRules' in rule && rule.cssRules) {
      yield* iterateCSSRules(rule.cssRules as CSSRuleList)
    }
  }
}

/**
 * Inject a <style> override that replaces CSS custom properties containing
 * oklch() values with their sRGB equivalents before calling html2canvas.
 *
 * html2canvas renders via Canvas 2D API which cannot parse oklch; the canvas
 * fillStyle serialisation trick converts them to hex for free.
 *
 * Recurses into @layer/@media/@supports blocks because Tailwind v4 defines
 * its :root variables inside `@layer theme { :root, :host { ... } }`.
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
      for (const rule of iterateCSSRules(sheet.cssRules)) {
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
 * Returns true for any node (or descendant of a node) that should be excluded
 * from screenshots. Using closest() ensures children of excluded containers
 * are filtered even when the capture library visits them individually.
 */
function shouldExclude(node: Node): boolean {
  return (
    node instanceof Element &&
    node.closest('[data-exclude-from-screenshot="true"]') !== null
  )
}

/**
 * Capture the current page as a PNG Blob.
 *
 * Both capture paths filter out elements marked with
 * data-exclude-from-screenshot="true" (e.g. modal overlays) so the screenshot
 * always shows the underlying page regardless of UI state at capture time.
 *
 * Strategy:
 *  1. Probe whether this browser supports SVG foreignObject rendering (cached).
 *  2. If yes, try html-to-image toBlob and validate the result isn't blank/black.
 *  3. Fall back to html2canvas (Canvas 2D, no foreignObject) with oklch CSS
 *     variable normalisation. This path always runs on Safari/iOS.
 *
 * Returns null only if all approaches fail.
 */
export async function captureScreenshot(): Promise<Blob | null> {
  const canUseForeignObject = await getForeignObjectSupport()

  if (canUseForeignObject) {
    try {
      const blob = await toBlob(document.body, {
        skipFonts: true,
        filter: (node) => !shouldExclude(node),
      })
      if (blob !== null && !(await blobLooksBlankOrBlack(blob))) {
        return blob
      }
    } catch {
      // fall through to html2canvas
    }
  }

  // html2canvas fallback — Canvas 2D rendering, no foreignObject dependency.
  // Dynamically imported so it doesn't bloat the main bundle on Chrome/Firefox.
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
      allowTaint: false,
      scale: Math.min(window.devicePixelRatio ?? 1, 2),
      logging: false,
      ignoreElements: shouldExclude,
    })
    return new Promise<Blob | null>(resolve => {
      try {
        canvas.toBlob(blob => resolve(blob), 'image/png')
      } catch {
        resolve(null)
      }
    })
  } catch {
    return null
  } finally {
    if (overrideStyle) {
      document.head.removeChild(overrideStyle)
    }
  }
}
