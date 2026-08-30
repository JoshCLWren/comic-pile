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
    | 'dialog-scroll-path'
    | 'element-collision'
    | 'large-blank-region'
  severity: 'warning'
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
    const doc = document.documentElement

    const rectOf = (element: Element) => {
      const rect = element.getBoundingClientRect()
      return {
        top: Math.round(rect.top * 10) / 10,
        right: Math.round(rect.right * 10) / 10,
        bottom: Math.round(rect.bottom * 10) / 10,
        left: Math.round(rect.left * 10) / 10,
        width: Math.round(rect.width * 10) / 10,
        height: Math.round(rect.height * 10) / 10,
      }
    }

    const isVisible = (element: HTMLElement) => {
      const style = window.getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number.parseFloat(style.opacity || '1') > 0
        && rect.width > 1
        && rect.height > 1
    }

    const describe = (element: HTMLElement) => {
      const role = element.getAttribute('role')
      const aria = element.getAttribute('aria-label')
      const testId = element.getAttribute('data-testid')
      const text = (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)
      const identity = [
        element.tagName.toLowerCase(),
        role ? `role=${role}` : '',
        aria ? `aria-label=${aria}` : '',
        testId ? `data-testid=${testId}` : '',
        text ? `text=${JSON.stringify(text)}` : '',
      ].filter(Boolean)
      return identity.join(' ')
    }

    const addFinding = (
      kind: AuditFinding['kind'],
      message: string,
      elements: HTMLElement[],
      measurements: AuditFinding['measurements'],
    ) => {
      if (findings.length >= 100) return
      findings.push({
        kind,
        severity: 'warning',
        message,
        elements: elements.map(describe),
        measurements,
      })
    }

    if (doc.scrollWidth > viewportWidth + 2) {
      addFinding(
        'horizontal-overflow',
        'The rendered document is wider than the viewport.',
        [document.body],
        {
          scrollWidth: doc.scrollWidth,
          viewportWidth,
          overflowPx: doc.scrollWidth - viewportWidth,
        },
      )
    }

    const meaningful = Array.from(document.querySelectorAll<HTMLElement>(
      'main, main h1, main h2, main h3, main button, main a, main input, main select, main textarea, main [role="button"], main [role="dialog"]',
    )).filter(isVisible).slice(0, 160)

    const chrome = Array.from(document.querySelectorAll<HTMLElement>('body *'))
      .filter((element) => {
        if (!isVisible(element)) return false
        const position = window.getComputedStyle(element).position
        return position === 'fixed' || position === 'sticky'
      })
      .slice(0, 40)

    for (const overlay of chrome) {
      const overlayRect = overlay.getBoundingClientRect()
      for (const target of meaningful) {
        if (overlay === target || overlay.contains(target) || target.contains(overlay)) continue
        const targetRect = target.getBoundingClientRect()
        const overlapWidth = Math.max(0, Math.min(overlayRect.right, targetRect.right) - Math.max(overlayRect.left, targetRect.left))
        const overlapHeight = Math.max(0, Math.min(overlayRect.bottom, targetRect.bottom) - Math.max(overlayRect.top, targetRect.top))
        const overlapArea = overlapWidth * overlapHeight
        if (overlapArea < 64) continue
        addFinding(
          'chrome-overlap',
          'Fixed or sticky chrome intersects meaningful page content.',
          [overlay, target],
          {
            overlapWidth: Math.round(overlapWidth * 10) / 10,
            overlapHeight: Math.round(overlapHeight * 10) / 10,
            overlapArea: Math.round(overlapArea),
            chromePosition: window.getComputedStyle(overlay).position,
          },
        )
        break
      }
    }

    const candidateChildren = Array.from(document.querySelectorAll<HTMLElement>(
      'main button, main a, main input, main select, main textarea, main [role="button"], [role="dialog"] button, [role="dialog"] input, [role="dialog"] select',
    )).filter(isVisible).slice(0, 160)

    for (const element of candidateChildren) {
      const container = element.parentElement?.closest<HTMLElement>('main, section, article, form, [role="dialog"]') ?? null
      if (!container || !isVisible(container)) continue
      const elementRect = element.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()
      const escapesHorizontally = elementRect.left < containerRect.left - 2 || elementRect.right > containerRect.right + 2
      if (escapesHorizontally) {
        addFinding(
          'container-escape',
          'An interactive element extends beyond its nearest semantic container.',
          [element, container],
          {
            elementLeft: Math.round(elementRect.left),
            elementRight: Math.round(elementRect.right),
            containerLeft: Math.round(containerRect.left),
            containerRight: Math.round(containerRect.right),
          },
        )
      }

      let ancestor = element.parentElement
      while (ancestor && ancestor !== document.body) {
        const style = window.getComputedStyle(ancestor)
        const overflowClipsX = style.overflowX === 'hidden' || style.overflowX === 'clip'
        const overflowClipsY = style.overflowY === 'hidden' || style.overflowY === 'clip'
        if (overflowClipsX || overflowClipsY) {
          const ancestorRect = ancestor.getBoundingClientRect()
          const clippedX = overflowClipsX && (elementRect.left < ancestorRect.left - 1 || elementRect.right > ancestorRect.right + 1)
          const clippedY = overflowClipsY && (elementRect.top < ancestorRect.top - 1 || elementRect.bottom > ancestorRect.bottom + 1)
          if (clippedX || clippedY) {
            addFinding(
              'clipped-action',
              'An interactive control is clipped by an ancestor without a scrolling path on that axis.',
              [element, ancestor],
              {
                clippedX,
                clippedY,
                ancestorOverflowX: style.overflowX,
                ancestorOverflowY: style.overflowY,
              },
            )
            break
          }
        }
        ancestor = ancestor.parentElement
      }
    }

    const dialogs = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).filter(isVisible)
    for (const dialog of dialogs) {
      const rect = dialog.getBoundingClientRect()
      if (rect.height <= viewportHeight - 8 && rect.top >= 0 && rect.bottom <= viewportHeight) continue
      const scrollContainers = [dialog, ...Array.from(dialog.querySelectorAll<HTMLElement>('*'))]
      const hasScrollPath = scrollContainers.some((element) => {
        const style = window.getComputedStyle(element)
        return (style.overflowY === 'auto' || style.overflowY === 'scroll')
          && element.scrollHeight > element.clientHeight + 1
      })
      if (!hasScrollPath) {
        addFinding(
          'dialog-scroll-path',
          'A dialog exceeds the usable viewport without an internal vertical scrolling path.',
          [dialog],
          {
            dialogTop: Math.round(rect.top),
            dialogBottom: Math.round(rect.bottom),
            dialogHeight: Math.round(rect.height),
            viewportHeight,
          },
        )
      }
    }

    const collisionCandidates = candidateChildren.slice(0, 80)
    let collisionCount = 0
    for (let index = 0; index < collisionCandidates.length && collisionCount < 12; index += 1) {
      const first = collisionCandidates[index]
      const firstRect = first.getBoundingClientRect()
      for (let otherIndex = index + 1; otherIndex < collisionCandidates.length && collisionCount < 12; otherIndex += 1) {
        const second = collisionCandidates[otherIndex]
        if (first.contains(second) || second.contains(first)) continue
        const secondRect = second.getBoundingClientRect()
        const overlapWidth = Math.max(0, Math.min(firstRect.right, secondRect.right) - Math.max(firstRect.left, secondRect.left))
        const overlapHeight = Math.max(0, Math.min(firstRect.bottom, secondRect.bottom) - Math.max(firstRect.top, secondRect.top))
        const overlapArea = overlapWidth * overlapHeight
        const smallerArea = Math.min(firstRect.width * firstRect.height, secondRect.width * secondRect.height)
        if (smallerArea <= 0 || overlapArea / smallerArea < 0.3) continue
        addFinding(
          'element-collision',
          'Two independent interactive controls substantially overlap.',
          [first, second],
          {
            overlapArea: Math.round(overlapArea),
            smallerElementArea: Math.round(smallerArea),
            overlapRatio: Math.round((overlapArea / smallerArea) * 1000) / 1000,
          },
        )
        collisionCount += 1
      }
    }

    if (auditContext.checkBlankRegions) {
      const main = document.querySelector<HTMLElement>('main')
      const blocks = main
        ? Array.from(main.children)
          .filter((child): child is HTMLElement => child instanceof HTMLElement && isVisible(child))
          .map((child) => ({ element: child, rect: child.getBoundingClientRect() }))
          .sort((first, second) => first.rect.top - second.rect.top)
        : []
      const threshold = Math.max(240, viewportHeight * 0.35)
      for (let index = 1; index < blocks.length; index += 1) {
        const previous = blocks[index - 1]
        const current = blocks[index]
        const gap = current.rect.top - previous.rect.bottom
        if (gap > threshold) {
          addFinding(
            'large-blank-region',
            'Stable fixture content contains a large vertical gap between primary page blocks.',
            [previous.element, current.element],
            {
              gapPx: Math.round(gap),
              thresholdPx: Math.round(threshold),
              viewportHeight,
            },
          )
        }
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
    ] as const

    const styleSamples = Array.from(document.querySelectorAll<HTMLElement>(
      'main, header, nav, section, article, [role="dialog"], button, a, input, select, textarea, [role="button"]',
    )).filter(isVisible).slice(0, 220)
    const inventory = new Map<string, StyleInventoryEntry>()
    for (const element of styleSamples) {
      const style = window.getComputedStyle(element)
      const example = describe(element)
      for (const [category, property] of styleProperties) {
        const value = style.getPropertyValue(property).trim()
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
        scrollWidth: doc.scrollWidth,
        scrollHeight: doc.scrollHeight,
        clientWidth: doc.clientWidth,
        clientHeight: doc.clientHeight,
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
    lines.push(
      `| ${escapeTableCell(result.scenario)} | \`${escapeTableCell(result.route)}\` | ${result.viewport.name} (${result.viewport.width}x${result.viewport.height}) | \`${escapeTableCell(result.screenshot)}\` | ${result.findings.length} | ${result.document.scrollWidth}x${result.document.scrollHeight} |`,
    )
  }

  lines.push('', '## Findings', '')
  if (warningCount === 0) {
    lines.push('No diagnostic geometry warnings were emitted for these stable states.', '')
  } else {
    for (const result of report.results.filter((entry) => entry.findings.length > 0)) {
      lines.push(`### ${result.scenario} at ${result.viewport.name}`, '')
      for (const finding of result.findings) {
        lines.push(`- **${finding.kind}**: ${finding.message}`)
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
      lines.push(
        `| ${escapeTableCell(entry.category)} | ${escapeTableCell(entry.property)} | \`${escapeTableCell(entry.value)}\` | ${entry.count} | ${escapeTableCell(entry.examples.join('; '))} |`,
      )
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
