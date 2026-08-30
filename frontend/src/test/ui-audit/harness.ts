import type { Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

export type AuditViewport = {
  name: string
  width: number
  height: number
}

export type AuditFinding = {
  kind:
    | 'horizontal-overflow'
    | 'chrome-overlap'
    | 'container-escape'
    | 'clipped-action'
    | 'unreachable-action'
    | 'dialog-scroll-path'
    | 'element-collision'
    | 'large-blank-region'
  severity: 'warning'
  confidence: 'high' | 'medium'
  message: string
  elements: string[]
  measurements: Record<string, string | number | boolean | null>
}

export type StyleInventoryEntry = {
  category: string
  property: string
  value: string
  count: number
  examples: string[]
}

export type AuditPageResult = {
  scenario: string
  route: string
  viewport: AuditViewport
  document: {
    scrollWidth: number
    scrollHeight: number
    clientWidth: number
    clientHeight: number
  }
  findings: AuditFinding[]
  styleInventory: StyleInventoryEntry[]
  screenshot: string
}

export type AuditReport = {
  schemaVersion: 1
  generatedAt: string
  fixture: string
  results: AuditPageResult[]
}

type AuditCaptureContext = {
  scenario: string
  route: string
  viewport: AuditViewport
  checkBlankRegions: boolean
}

export async function captureRenderedAudit(
  page: Page,
  context: AuditCaptureContext,
): Promise<Omit<AuditPageResult, 'screenshot'>> {
  return page.evaluate<Omit<AuditPageResult, 'screenshot'>, AuditCaptureContext>((auditContext) => {
    const findings: AuditFinding[] = []
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const documentElement = document.documentElement

    const isVisible = (element: HTMLElement): boolean => {
      const style = window.getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number.parseFloat(style.opacity || '1') > 0
        && rect.width > 1
        && rect.height > 1
    }

    const describe = (element: HTMLElement): string => {
      const role = element.getAttribute('role')
      const ariaLabel = element.getAttribute('aria-label')
      const testId = element.getAttribute('data-testid')
      const text = (element.innerText || element.textContent || '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 80)
      return [
        element.tagName.toLowerCase(),
        role ? `role=${role}` : '',
        ariaLabel ? `aria-label=${ariaLabel}` : '',
        testId ? `data-testid=${testId}` : '',
        text ? `text=${JSON.stringify(text)}` : '',
      ].filter(Boolean).join(' ')
    }

    const round = (value: number): number => Math.round(value * 10) / 10
    const intersection = (first: DOMRect, second: DOMRect) => {
      const width = Math.max(0, Math.min(first.right, second.right) - Math.max(first.left, second.left))
      const height = Math.max(0, Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top))
      return { width, height, area: width * height }
    }

    const addFinding = (
      kind: AuditFinding['kind'],
      confidence: AuditFinding['confidence'],
      message: string,
      elements: HTMLElement[],
      measurements: AuditFinding['measurements'],
    ): void => {
      if (findings.length >= 100) return
      findings.push({
        kind,
        severity: 'warning',
        confidence,
        message,
        elements: elements.map(describe),
        measurements,
      })
    }

    if (documentElement.scrollWidth > viewportWidth + 2) {
      addFinding('horizontal-overflow', 'high', 'The rendered document is wider than the viewport.', [document.body], {
        scrollWidth: documentElement.scrollWidth,
        viewportWidth,
        overflowPx: documentElement.scrollWidth - viewportWidth,
      })
    }

    const meaningful = Array.from(document.querySelectorAll<HTMLElement>(
      'main, main h1, main h2, main h3, main button, main a, main input, main select, main textarea, main [role="button"], [role="dialog"]',
    )).filter(isVisible).slice(0, 180)

    const chrome = Array.from(document.querySelectorAll<HTMLElement>('body *'))
      .filter((element) => {
        if (!isVisible(element)) return false
        const position = window.getComputedStyle(element).position
        return position === 'fixed' || position === 'sticky'
      })
      .slice(0, 50)

    for (const overlay of chrome) {
      const overlayRect = overlay.getBoundingClientRect()
      for (const target of meaningful) {
        if (overlay === target || overlay.contains(target) || target.contains(overlay)) continue
        const overlap = intersection(overlayRect, target.getBoundingClientRect())
        if (overlap.area < 64) continue
        addFinding('chrome-overlap', 'high', 'Fixed or sticky chrome intersects meaningful page content.', [overlay, target], {
          overlapWidth: round(overlap.width),
          overlapHeight: round(overlap.height),
          overlapArea: Math.round(overlap.area),
          chromePosition: window.getComputedStyle(overlay).position,
        })
        break
      }
    }

    const controls = Array.from(document.querySelectorAll<HTMLElement>(
      'main button, main a, main input, main select, main textarea, main [role="button"], [role="dialog"] button, [role="dialog"] input, [role="dialog"] select, [role="dialog"] textarea',
    )).filter(isVisible).slice(0, 180)

    for (const element of controls) {
      const elementRect = element.getBoundingClientRect()
      const elementStyle = window.getComputedStyle(element)
      const fixedToViewport = elementStyle.position === 'fixed' || elementStyle.position === 'sticky'
      const outsideHorizontalViewport = elementRect.right <= 0 || elementRect.left >= viewportWidth
      const outsideVerticalViewport = elementRect.bottom <= 0 || elementRect.top >= viewportHeight
      const outsideDocumentWidth = elementRect.right <= 0 || elementRect.left >= documentElement.scrollWidth

      if (outsideDocumentWidth || (fixedToViewport && (outsideHorizontalViewport || outsideVerticalViewport))) {
        addFinding('unreachable-action', 'high', 'An interactive control is rendered outside its reachable viewport or document width.', [element], {
          elementLeft: round(elementRect.left),
          elementTop: round(elementRect.top),
          elementRight: round(elementRect.right),
          elementBottom: round(elementRect.bottom),
          viewportWidth,
          viewportHeight,
          documentScrollWidth: documentElement.scrollWidth,
          position: elementStyle.position,
        })
      }

      const container = element.parentElement?.closest<HTMLElement>('main, section, article, form, [role="dialog"]') ?? null
      if (container && isVisible(container)) {
        const containerRect = container.getBoundingClientRect()
        if (elementRect.left < containerRect.left - 2 || elementRect.right > containerRect.right + 2) {
          addFinding('container-escape', 'medium', 'An interactive element extends beyond its nearest semantic container.', [element, container], {
            elementLeft: round(elementRect.left),
            elementRight: round(elementRect.right),
            containerLeft: round(containerRect.left),
            containerRight: round(containerRect.right),
          })
        }
      }

      let ancestor = element.parentElement
      while (ancestor && ancestor !== document.body) {
        const style = window.getComputedStyle(ancestor)
        const clipsX = style.overflowX === 'hidden' || style.overflowX === 'clip'
        const clipsY = style.overflowY === 'hidden' || style.overflowY === 'clip'
        if (clipsX || clipsY) {
          const ancestorRect = ancestor.getBoundingClientRect()
          const clippedX = clipsX && (elementRect.left < ancestorRect.left - 1 || elementRect.right > ancestorRect.right + 1)
          const clippedY = clipsY && (elementRect.top < ancestorRect.top - 1 || elementRect.bottom > ancestorRect.bottom + 1)
          if (clippedX || clippedY) {
            addFinding('clipped-action', 'high', 'An interactive control is clipped by an ancestor without a scrolling path on that axis.', [element, ancestor], {
              clippedX,
              clippedY,
              ancestorOverflowX: style.overflowX,
              ancestorOverflowY: style.overflowY,
            })
            break
          }
        }
        ancestor = ancestor.parentElement
      }
    }

    const dialogs = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).filter(isVisible)
    for (const dialog of dialogs) {
      const dialogRect = dialog.getBoundingClientRect()
      const exceedsViewport = dialogRect.top < 0
        || dialogRect.bottom > viewportHeight
        || dialogRect.height > viewportHeight - 8
      if (!exceedsViewport) continue
      const scrollContainers = [dialog, ...Array.from(dialog.querySelectorAll<HTMLElement>('*'))]
      const hasScrollPath = scrollContainers.some((element) => {
        const style = window.getComputedStyle(element)
        return (style.overflowY === 'auto' || style.overflowY === 'scroll')
          && element.scrollHeight > element.clientHeight + 1
      })
      if (!hasScrollPath) {
        addFinding('dialog-scroll-path', 'high', 'A dialog exceeds the usable viewport without an internal vertical scrolling path.', [dialog], {
          dialogTop: round(dialogRect.top),
          dialogBottom: round(dialogRect.bottom),
          dialogHeight: round(dialogRect.height),
          viewportHeight,
        })
      }
    }

    const collisionCandidates = controls.slice(0, 90)
    let collisionCount = 0
    for (let index = 0; index < collisionCandidates.length && collisionCount < 12; index += 1) {
      const first = collisionCandidates[index]
      const firstRect = first.getBoundingClientRect()
      for (let otherIndex = index + 1; otherIndex < collisionCandidates.length && collisionCount < 12; otherIndex += 1) {
        const second = collisionCandidates[otherIndex]
        if (first.contains(second) || second.contains(first)) continue
        const secondRect = second.getBoundingClientRect()
        const overlap = intersection(firstRect, secondRect)
        const smallerArea = Math.min(firstRect.width * firstRect.height, secondRect.width * secondRect.height)
        if (smallerArea <= 0 || overlap.area / smallerArea < 0.3) continue
        addFinding('element-collision', 'medium', 'Two independent interactive controls substantially overlap.', [first, second], {
          overlapArea: Math.round(overlap.area),
          smallerElementArea: Math.round(smallerArea),
          overlapRatio: Math.round((overlap.area / smallerArea) * 1000) / 1000,
        })
        collisionCount += 1
      }
    }

    if (auditContext.checkBlankRegions) {
      const main = document.querySelector<HTMLElement>('main')
      const blocks = main
        ? Array.from(main.querySelectorAll<HTMLElement>(':scope > *, :scope > * > section, :scope > * > article'))
          .filter(isVisible)
          .map((element) => ({ element, rect: element.getBoundingClientRect() }))
          .sort((first, second) => first.rect.top - second.rect.top)
        : []
      const threshold = Math.max(240, viewportHeight * 0.35)
      for (let index = 1; index < blocks.length; index += 1) {
        const previous = blocks[index - 1]
        const current = blocks[index]
        const gap = current.rect.top - previous.rect.bottom
        if (gap <= threshold) continue
        addFinding('large-blank-region', 'medium', 'Stable fixture content contains a large vertical gap between primary page blocks.', [previous.element, current.element], {
          gapPx: Math.round(gap),
          thresholdPx: Math.round(threshold),
          viewportHeight,
        })
      }
    }

    const styleProperties = [
      ['radii', 'border-radius'],
      ['typography', 'font-family'],
      ['typography', 'font-size'],
      ['typography', 'font-weight'],
      ['typography', 'line-height'],
      ['typography', 'letter-spacing'],
      ['colors', 'color'],
      ['colors', 'background-color'],
      ['colors', 'border-color'],
      ['shadows', 'box-shadow'],
      ['spacing', 'padding-top'],
      ['spacing', 'padding-right'],
      ['spacing', 'padding-bottom'],
      ['spacing', 'padding-left'],
      ['spacing', 'margin-top'],
      ['spacing', 'margin-bottom'],
      ['spacing', 'gap'],
      ['controls', 'min-height'],
      ['controls', 'height'],
      ['controls', 'border-width'],
      ['panels', 'background-color'],
      ['panels', 'border-radius'],
      ['panels', 'border-color'],
      ['panels', 'box-shadow'],
    ] as const

    const styleSamples = Array.from(document.querySelectorAll<HTMLElement>(
      'main, main > div, header, nav, section, article, [role="dialog"], button, a, input, select, textarea, [role="button"]',
    )).filter(isVisible).slice(0, 240)
    const inventory = new Map<string, StyleInventoryEntry>()
    for (const element of styleSamples) {
      const computed = window.getComputedStyle(element)
      const example = describe(element)
      const isPanel = element.matches('main, main > div, section, article, [role="dialog"]')
      const isControl = element.matches('button, a, input, select, textarea, [role="button"]')
      for (const [category, property] of styleProperties) {
        if (category === 'panels' && !isPanel) continue
        if (category === 'controls' && !isControl) continue
        const value = computed.getPropertyValue(property).trim()
        if (!value) continue
        const key = `${category}\u0000${property}\u0000${value}`
        const existing = inventory.get(key)
        if (existing) {
          existing.count += 1
          if (existing.examples.length < 3 && !existing.examples.includes(example)) existing.examples.push(example)
        } else {
          inventory.set(key, { category, property, value, count: 1, examples: [example] })
        }
      }
    }

    return {
      scenario: auditContext.scenario,
      route: auditContext.route,
      viewport: auditContext.viewport,
      document: {
        scrollWidth: documentElement.scrollWidth,
        scrollHeight: documentElement.scrollHeight,
        clientWidth: documentElement.clientWidth,
        clientHeight: documentElement.clientHeight,
      },
      findings,
      styleInventory: Array.from(inventory.values()).sort((first, second) => {
        if (first.category !== second.category) return first.category.localeCompare(second.category)
        if (first.property !== second.property) return first.property.localeCompare(second.property)
        return second.count - first.count
      }),
    }
  }, context)
}

function escapeTableCell(value: string): string {
  return value.replace(/\|/g, '\\|').replace(/\n/g, ' ')
}

export function renderAuditMarkdown(report: AuditReport): string {
  const warningCount = report.results.reduce((total, result) => total + result.findings.length, 0)
  const lines = [
    '# Comic Pile UI visual and geometry audit',
    '',
    `Generated: ${report.generatedAt}`,
    `Fixture: ${report.fixture}`,
    `Scenarios: ${report.results.length}`,
    `Diagnostic warnings: ${warningCount}`,
    '',
    '> Audit warnings are rendered evidence for investigation. They do not fail the harness by themselves. Navigation, fixture, browser-health, capture, or report-generation failures still fail the command.',
    '',
    '## Coverage',
    '',
    '| State | Route | Viewport | Screenshot | Warnings | Document |',
    '| --- | --- | --- | --- | ---: | --- |',
  ]

  for (const result of report.results) {
    lines.push(`| ${escapeTableCell(result.scenario)} | \`${escapeTableCell(result.route)}\` | ${result.viewport.name} (${result.viewport.width}x${result.viewport.height}) | \`${escapeTableCell(result.screenshot)}\` | ${result.findings.length} | ${result.document.scrollWidth}x${result.document.scrollHeight} |`)
  }

  lines.push('', '## Findings', '')
  if (warningCount === 0) {
    lines.push('No diagnostic geometry warnings were emitted for these stable states.', '')
  } else {
    for (const result of report.results.filter((entry) => entry.findings.length > 0)) {
      lines.push(`### ${result.scenario} at ${result.viewport.name}`, '')
      for (const finding of result.findings) {
        lines.push(`- **${finding.kind}** (${finding.confidence} confidence): ${finding.message}`)
        lines.push(`  - route: \`${result.route}\``)
        lines.push(`  - elements: ${finding.elements.map((element) => `\`${element}\``).join(', ')}`)
        lines.push(`  - measurements: \`${JSON.stringify(finding.measurements)}\``)
      }
      lines.push('')
    }
  }

  lines.push('## Computed-style inventory', '')
  lines.push('The inventory is descriptive, not a defect list. Repeated or unique values are evidence only.', '')
  for (const result of report.results) {
    lines.push(`### ${result.scenario} at ${result.viewport.name}`, '')
    lines.push('| Category | Property | Value | Count | Examples |')
    lines.push('| --- | --- | --- | ---: | --- |')
    for (const entry of result.styleInventory) {
      lines.push(`| ${escapeTableCell(entry.category)} | ${escapeTableCell(entry.property)} | \`${escapeTableCell(entry.value)}\` | ${entry.count} | ${escapeTableCell(entry.examples.join('; '))} |`)
    }
    lines.push('')
  }

  return `${lines.join('\n')}\n`
}

export async function writeAuditReport(report: AuditReport, outputDirectory: string): Promise<void> {
  await mkdir(outputDirectory, { recursive: true })
  await writeFile(join(outputDirectory, 'report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  await writeFile(join(outputDirectory, 'report.md'), renderAuditMarkdown(report), 'utf8')
}
