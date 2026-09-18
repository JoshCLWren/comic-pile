import { render } from '@testing-library/react'
import { it, describe } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../App'

import MigrationDialog from '../components/MigrationDialog'
import SimpleMigrationDialog from '../components/SimpleMigrationDialog'
import ContinuityPlansIndexPage from '../pages/ContinuityPlansIndexPage'
import Navigation from '../components/Navigation'

const FORBIDDEN_PATTERNS = [
  { mode: 'role-dialog', query: '[role="dialog"]' },
  { mode: 'aria-modal', query: '[aria-modal="true"]' },
  { mode: 'fixed-inset-0', query: '.fixed.inset-0' },
] as const

type ForbiddenPattern = (typeof FORBIDDEN_PATTERNS)[0]

const KNOWN_DEBT_ALLOWLIST = new Set([
  'MigrationDialog',
  'SimpleMigrationDialog',
  'ContinuityPlansIndexPage',
  'Navigation',
])

function hasForbiddenPatternInElement(
  element: HTMLElement,
): { mode: string } | null {
  for (const pattern of FORBIDDEN_PATTERNS) {
    if (element.matches(pattern.query)) {
      return { mode: pattern.mode }
    }
  }
  return null
}

function isKnownDebt(componentName: string): boolean {
  return KNOWN_DEBT_ALLOWLIST.has(componentName)
}

function testComponent(
  name: string,
  component: React.ReactElement,
  allowlisted: boolean,
) {
  it(`${name} has only allowlisted forbidden patterns`, () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/']}>
        {allowlisted ? component : (
          <AuthProvider>
            {component}
          </AuthProvider>
        )}
      </MemoryRouter>,
    )

    const allElements = container.querySelectorAll('*')

    for (const el of allElements) {
      const elementNode = el as HTMLElement
      if (!elementNode) continue

      const pattern = hasForbiddenPatternInElement(elementNode)
      if (pattern) {
        if (!isKnownDebt(name)) {
          throw new Error(
            `${name} contains a forbidden overlay pattern: ${pattern.mode}. ` +
              `If this is known debt, add "${name}" to the KNOWN_DEBT_ALLOWLIST.`,
          )
        }
        // allowlisted known debt - ok
      }
    }
  })
}

describe('Overlay conformance', () => {
  testComponent(
    'MigrationDialog',
    <MigrationDialog
      thread={{ id: 1, title: 'Test' }}
      onComplete={() => {}}
      onSkip={() => {}}
      onClose={() => {}}
    />,
    true,
  )

  testComponent(
    'SimpleMigrationDialog',
    <SimpleMigrationDialog
      threadTitle="Test"
      onComplete={() => {}}
      onClose={() => {}}
    />,
    true,
  )

  testComponent(
    'ContinuityPlansIndexPage',
    <ContinuityPlansIndexPage />,
    true,
  )

  testComponent(
    'Navigation',
    <Navigation onBugReportSubmit={() => {}} />,
    true,
  )
})