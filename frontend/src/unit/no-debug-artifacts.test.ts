import { readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'
import { expect, it } from 'vitest'

const SOURCE_ROOT = join(import.meta.dirname, '..')
const THIS_FILE = import.meta.filename

const DEBUG_PATTERNS = [
  { pattern: '127.0.0.1', label: 'localhost telemetry endpoint' },
  { pattern: '#region agent log', label: 'agent debug block' },
  { pattern: '[roll-debug]', label: 'debug console label' },
]

function collectSourceFiles(dir) {
  const files = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      files.push(...collectSourceFiles(full))
    } else if (/\.(js|jsx|ts|tsx)$/.test(entry) && full !== THIS_FILE) {
      files.push(full)
    }
  }
  return files
}

it('source files contain no debug artifact patterns', () => {
  const files = collectSourceFiles(SOURCE_ROOT)
  const violations = []

  for (const file of files) {
    const content = readFileSync(file, 'utf-8')
    for (const { pattern, label } of DEBUG_PATTERNS) {
      if (content.includes(pattern)) {
        violations.push(`${file}: found "${pattern}" (${label})`)
      }
    }
  }

  expect(violations, violations.join('\n')).toHaveLength(0)
})
