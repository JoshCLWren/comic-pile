import { describe, expect, it } from 'vitest'
import { renderAuditMarkdown, type AuditReport } from '../test/ui-audit/harness'

function sampleReport(): AuditReport {
  return {
    schemaVersion: 1,
    generatedAt: '2026-08-30T12:00:00.000Z',
    fixture: 'stable fixture',
    results: [
      {
        scenario: 'queue',
        route: '/queue',
        viewport: { name: 'phone', width: 390, height: 844 },
        document: {
          scrollWidth: 410,
          scrollHeight: 1200,
          clientWidth: 390,
          clientHeight: 844,
        },
        findings: [
          {
            kind: 'horizontal-overflow',
            severity: 'warning',
            message: 'The rendered document is wider than the viewport.',
            elements: ['body text="Queue"'],
            measurements: {
              scrollWidth: 410,
              viewportWidth: 390,
              overflowPx: 20,
            },
          },
        ],
        styleInventory: [
          {
            category: 'radii',
            property: 'border-radius',
            value: '12px',
            count: 3,
            examples: ['button text="Read Now"'],
          },
        ],
        screenshot: 'screenshots/queue-phone-390x844.png',
      },
    ],
  }
}

describe('UI audit report rendering', () => {
  it('keeps diagnostic warnings distinct from harness failures', () => {
    const markdown = renderAuditMarkdown(sampleReport())

    expect(markdown).toContain('Diagnostic warnings: 1')
    expect(markdown).toContain('Audit warnings are rendered evidence for investigation')
    expect(markdown).toContain('do not fail the harness by themselves')
    expect(markdown).toContain('horizontal-overflow')
  })

  it('records enough state, viewport, element, measurement, screenshot, and style evidence to reproduce a finding', () => {
    const markdown = renderAuditMarkdown(sampleReport())

    expect(markdown).toContain('queue')
    expect(markdown).toContain('/queue')
    expect(markdown).toContain('phone (390x844)')
    expect(markdown).toContain('screenshots/queue-phone-390x844.png')
    expect(markdown).toContain('overflowPx')
    expect(markdown).toContain('body text=')
    expect(markdown).toContain('border-radius')
    expect(markdown).toContain('12px')
  })
})
