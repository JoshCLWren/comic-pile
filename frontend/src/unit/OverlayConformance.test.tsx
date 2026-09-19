import { readdirSync, readFileSync, statSync } from 'fs'
import { join, relative, sep } from 'path'
import { describe, expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')
const THIS_FILE = import.meta.filename

/**
 * Overlay conformance for #2577.
 *
 * Ownership rule (see frontend/AGENTS.md): dialogs use `Modal`;
 * menus/popovers use `OverlayPortal` with `layer="menu"` (or a thin shared
 * Menu primitive built on it). Ad-hoc `role="dialog"` / `aria-modal` /
 * full-viewport `fixed inset-0` overlays outside the approved components are
 * forbidden. The files below are known debt allowlisted until the follow-up
 * migration ticket lands; each allowlist entry must still match its markers
 * so a completed migration fails loudly and the entry gets removed.
 */

const APPROVED_FILES = new Set([
  'components/Modal.tsx',
  'components/OverlayPortal.tsx',
  'components/PositionMenu.tsx',
])

const DIALOG_PATTERNS = [
  { label: 'role="dialog"', regex: /role\s*=\s*["']dialog["']/ },
  { label: 'aria-modal', regex: /aria-modal/ },
  { label: 'fixed inset-0 overlay', regex: /fixed[^\n]*inset-0|inset-0[^\n]*fixed/ },
  { label: 'migration-dialog__overlay class', regex: /migration-dialog__overlay/ },
] as const

const MORE_MENU_PATTERN = {
  label: 'ad-hoc fixed z-50 menu',
  regex: /fixed[^\n]*z-50/,
} as const

type DebtEntry = {
  file: string
  markers: readonly { label: string; regex: RegExp }[]
}

const KNOWN_DEBT: DebtEntry[] = [
  {
    file: 'components/MigrationDialog.tsx',
    markers: [DIALOG_PATTERNS[0], DIALOG_PATTERNS[1], DIALOG_PATTERNS[3]],
  },
  {
    file: 'components/SimpleMigrationDialog.tsx',
    markers: [DIALOG_PATTERNS[0], DIALOG_PATTERNS[1], DIALOG_PATTERNS[3]],
  },
  {
    file: 'pages/ContinuityPlansIndexPage.tsx',
    markers: [DIALOG_PATTERNS[0], DIALOG_PATTERNS[1], DIALOG_PATTERNS[2]],
  },
  {
    file: 'components/Navigation.tsx',
    markers: [MORE_MENU_PATTERN],
  },
]

const KNOWN_DEBT_FILES = new Set(KNOWN_DEBT.map((entry) => entry.file))

function toSourcePath(full: string): string {
  return relative(SOURCE_ROOT, full).split(sep).join('/')
}

function isScannedFile(full: string, entry: string): boolean {
  if (full === THIS_FILE) return false
  if (!/\.(js|jsx|ts|tsx)$/.test(entry)) return false
  if (entry.includes('.test.') || entry.includes('.spec.')) return false
  return true
}

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      const rel = toSourcePath(full)
      if (rel === 'unit' || rel === 'test' || rel.startsWith('unit/') || rel.startsWith('test/')) {
        continue
      }
      files.push(...collectSourceFiles(full))
    } else if (isScannedFile(full, entry)) {
      files.push(full)
    }
  }
  return files
}

describe('Overlay conformance', () => {
  it('no non-allowlisted source file introduces an ad-hoc dialog overlay', () => {
    const violations: string[] = []
    for (const file of collectSourceFiles(SOURCE_ROOT)) {
      const rel = toSourcePath(file)
      if (APPROVED_FILES.has(rel) || KNOWN_DEBT_FILES.has(rel)) continue
      const content = readFileSync(file, 'utf-8')
      for (const { label, regex } of DIALOG_PATTERNS) {
        if (regex.test(content)) {
          violations.push(`${rel}: found forbidden overlay pattern (${label})`)
        }
      }
    }
    expect(violations, violations.join('\n')).toHaveLength(0)
  })

  it('every allowlisted debt file still matches its markers (shrink on migrate)', () => {
    const stale: string[] = []
    for (const { file, markers } of KNOWN_DEBT) {
      const content = readFileSync(join(SOURCE_ROOT, file), 'utf-8')
      for (const { label, regex } of markers) {
        if (!regex.test(content)) {
          stale.push(
            `${file}: no longer contains (${label}); migration landed, remove it from KNOWN_DEBT`,
          )
        }
      }
    }
    expect(stale, stale.join('\n')).toHaveLength(0)
  })
})
