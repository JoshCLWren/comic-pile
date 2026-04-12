import { toBlob } from 'html-to-image'

export interface ScreenshotDiagnostics {
  timestamp: string
  userAgent: string
  target: { id: string; tag: string; children: number; rect: DOMRect }
  environment: { pixelRatio: number; devicePixelRatio: number; canUseForeignObject: boolean }
  captureAttempts: Array<{ method: string; success: boolean; error?: string; size?: number; blank?: boolean }>
  ancestorChain: Array<{ tag: string; id: string; className: string; transform: string; filter: string; backdropFilter: string }>
}

const diagnostics: ScreenshotDiagnostics = {
  timestamp: new Date().toISOString(),
  userAgent: navigator.userAgent,
  target: { id: '', tag: '', children: 0, rect: new DOMRect() },
  environment: { pixelRatio: 0, devicePixelRatio: 0, canUseForeignObject: false },
  captureAttempts: [],
  ancestorChain: [],
}

function debugLog(message: string, data?: unknown) {
  console.log(`[SCREENSHOT] ${message}`, data ?? '')
}

function logAncestorChain(el: HTMLElement | null) {
  const chain = []
  let current: HTMLElement | null = el

  while (current && current !== document.body) {
    const style = getComputedStyle(current)
    const info = {
      tag: current.tagName,
      id: current.id,
      className: current.className,
      transform: style.transform,
      filter: style.filter,
      backdropFilter: (style as CSSStyleDeclaration & { backdropFilter?: string }).backdropFilter ?? 'n/a',
    }
    chain.push(info)
    current = current.parentElement
  }

  diagnostics.ancestorChain = chain
  return chain
}

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

function getForeignObjectSupport(): Promise<boolean> {
  if (!foreignObjectSupportPromise) {
    foreignObjectSupportPromise = supportsForeignObjectRendering()
  }
  return foreignObjectSupportPromise
}

async function blobLooksBlankOrBlack(
  blob: Blob,
  { sampleSize = 8, uniformTolerance = 8 }: { sampleSize?: number; uniformTolerance?: number } = {}
): Promise<boolean> {
  try {
    const img = new Image()
    const url = URL.createObjectURL(blob)

    try {
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve()
        img.onerror = () => reject(new Error('blob decode failed'))
        img.src = url
      })
    } finally {
      URL.revokeObjectURL(url)
    }

    const canvas = document.createElement('canvas')
    canvas.width = sampleSize
    canvas.height = sampleSize

    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return true

    ctx.drawImage(img, 0, 0, sampleSize, sampleSize)
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

    debugLog('blob validation', { blackish: `${blackish}/${total}`, transparentish: `${transparentish}/${total}`, min, max, almostAllBlack, almostAllTransparent, nearlyUniform })

    return almostAllBlack || almostAllTransparent || nearlyUniform
  } catch {
    return true
  }
}

function* iterateCSSRules(rules: CSSRuleList): Generator<CSSRule> {
  for (const rule of Array.from(rules)) {
    yield rule
    if ('cssRules' in rule && rule.cssRules) {
      yield* iterateCSSRules(rule.cssRules as CSSRuleList)
    }
  }
}

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

export async function captureScreenshot(): Promise<{ blob: Blob | null; diagnostics: ScreenshotDiagnostics }> {
  debugLog('Starting capture')

  // Reset diagnostics
  diagnostics.timestamp = new Date().toISOString()
  diagnostics.captureAttempts = []

  // Capture from #root instead of document.body for better Safari compatibility
  const target = document.getElementById('root') ?? document.body
  diagnostics.target = {
    id: target.id,
    tag: target.tagName,
    children: target.children.length,
    rect: target.getBoundingClientRect(),
  }

  const pixelRatio = 1
  const canUseForeignObject = await getForeignObjectSupport()
  diagnostics.environment = { pixelRatio, devicePixelRatio: window.devicePixelRatio, canUseForeignObject }

  // Log ancestor chain to detect problematic styles
  logAncestorChain(target)

  debugLog('Target', diagnostics.target)
  debugLog('Environment', diagnostics.environment)

  // Add screenshot-mode class to strip problematic CSS
  document.documentElement.classList.add('screenshot-mode')

  // Force solid background to prevent transparency issues
  const prevBackground = target.style.backgroundColor
  target.style.backgroundColor = '#111827'

  try {
    debugLog('Trying html-to-image')
    const blob = await toBlob(target, {
      skipFonts: true,
      cacheBust: true,
      pixelRatio,
      filter: node => {
        const excluded = node instanceof HTMLElement && node.closest('[data-exclude-from-screenshot="true"]') !== null
        return !excluded
      },
    })

    diagnostics.captureAttempts.push({
      method: 'html-to-image',
      success: blob !== null,
      size: blob?.size,
    })

    debugLog('html-to-image result', { success: blob !== null, size: blob?.size })

    if (blob !== null) {
      const isBlank = await blobLooksBlankOrBlack(blob)
      diagnostics.captureAttempts[0].blank = isBlank
      debugLog('Blob validation', { isBlank })

      if (!isBlank) {
        debugLog('Using html-to-image blob', { size: blob.size })
        return { blob, diagnostics }
      }
      debugLog('html-to-image blob is blank')
    } else {
      debugLog('html-to-image returned null')
    }
  } catch (error) {
    diagnostics.captureAttempts.push({
      method: 'html-to-image',
      success: false,
      error: error instanceof Error ? error.message : String(error),
    })
    debugLog('html-to-image ERROR', { error: String(error) })
  } finally {
    document.documentElement.classList.remove('screenshot-mode')
    target.style.backgroundColor = prevBackground
  }

  debugLog('Trying html2canvas fallback')
  let html2canvas: typeof import('html2canvas').default
  try {
    html2canvas = (await import('html2canvas')).default
    debugLog('html2canvas imported successfully')
  } catch (error) {
    diagnostics.captureAttempts.push({
      method: 'html2canvas-import',
      success: false,
      error: String(error),
    })
    debugLog('Failed to import html2canvas', { error: String(error) })
    return { blob: null, diagnostics }
  }

  // Add screenshot-mode for html2canvas too
  document.documentElement.classList.add('screenshot-mode')

  const overrideStyle = injectOklchFallbacks()
  debugLog('oklch fallback injected', { injected: overrideStyle !== null })

  // Force solid background for html2canvas
  const prevBackgroundH2c = target.style.backgroundColor
  target.style.backgroundColor = '#111827'

  try {
    debugLog('html2canvas starting')

    const canvas = await html2canvas(target, {
      useCORS: true,
      allowTaint: false,
      scale: 1,
      logging: false,
      backgroundColor: '#111827',
      ignoreElements: (element) => {
        const excluded = element instanceof HTMLElement && element.closest('[data-exclude-from-screenshot="true"]') !== null
        return excluded
      },
    })

    diagnostics.captureAttempts.push({
      method: 'html2canvas',
      success: true,
      size: canvas.width * canvas.height * 4,
    })

    debugLog('html2canvas canvas created', { width: canvas.width, height: canvas.height })

    const blob = await new Promise<Blob | null>((resolve) => {
      try {
        canvas.toBlob((result) => resolve(result), 'image/png')
      } catch (e) {
        debugLog('canvas.toBlob error', { error: String(e) })
        resolve(null)
      }
    })

    if (blob) {
      debugLog('html2canvas blob created', { size: blob.size, type: blob.type })
    }

    return { blob, diagnostics }
  } catch (error) {
    diagnostics.captureAttempts.push({
      method: 'html2canvas',
      success: false,
      error: error instanceof Error ? error.message : String(error),
    })
    debugLog('html2canvas ERROR', { error: String(error) })
    return { blob: null, diagnostics }
  } finally {
    document.documentElement.classList.remove('screenshot-mode')
    overrideStyle?.remove()
    target.style.backgroundColor = prevBackgroundH2c
    debugLog('Cleaned up html2canvas')
  }
}
