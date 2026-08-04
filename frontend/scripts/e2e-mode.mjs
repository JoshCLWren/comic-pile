#!/usr/bin/env node

import { spawnSync } from 'node:child_process'

const SMOKE_SPECS = [
  'src/test/history.spec.ts',
  'src/test/issue-583-virtualized-grid.spec.ts',
  'src/test/roll-snooze-network.spec.ts',
]

function parseMode(value) {
  if (value === 'smoke' || value === 'affected' || value === 'full') return value
  throw new Error(`Unsupported E2E mode: ${value}`)
}

function affectedSpecs() {
  const configured = process.env.E2E_AFFECTED_SPECS?.trim()
  if (!configured) return SMOKE_SPECS
  return configured.split(',').map((value) => value.trim()).filter(Boolean)
}

function buildArgs(mode, extraArgs = []) {
  const args = ['playwright', 'test']
  if (mode === 'smoke') args.push(...SMOKE_SPECS)
  if (mode === 'affected') args.push(...affectedSpecs())

  const browser = process.env.E2E_BROWSER?.trim()
  if (browser && browser !== 'all') args.push(`--project=${browser}`)

  args.push(...extraArgs)
  return args
}

const mode = parseMode(process.argv[2] ?? 'smoke')
const printOnly = process.argv.includes('--print')
const extraArgs = process.argv.slice(3).filter((argument) => argument !== '--print')
const args = buildArgs(mode, extraArgs)

if (printOnly) {
  console.log(['pnpm', 'exec', ...args].join(' '))
  process.exit(0)
}

const result = spawnSync('pnpm', ['exec', ...args], {
  cwd: process.cwd(),
  env: process.env,
  stdio: 'inherit',
})

if (result.error) {
  console.error(result.error.message)
  process.exit(1)
}

process.exit(result.status ?? 1)
