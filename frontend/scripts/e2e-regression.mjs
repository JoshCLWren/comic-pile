#!/usr/bin/env node
// Inventory-driven Chromium regression runner (issue #1483).
//
// 1. Selects spec files from docs/e2e-behavior-inventory.yaml via
//    scripts/e2e_regression_select.py (the coverage source of truth).
// 2. Builds the frontend so the served assets match the repo.
// 3. Runs playwright with playwright.regression.config.ts against the
//    selection manifest, preserving traces/screenshots/video on failure.
//
// This runner never creates GitHub issues or labels; see
// docs/E2E_CHROMIUM_REGRESSION.md for the defect reconciliation path.
import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = fileURLToPath(new URL('../', import.meta.url))
const repositoryRoot = path.resolve(frontendRoot, '..')
const defaultOutput = path.join(frontendRoot, 'test-results', 'regression', 'selection.json')

export function parseArgs(argv) {
  const options = {
    scope: process.env.E2E_REGRESSION_SCOPE ?? 'p1-p2',
    workers: process.env.REGRESSION_WORKERS ?? null,
    skipBuild: process.env.E2E_REGRESSION_SKIP_BUILD === '1',
    list: false,
    help: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--scope') {
      const value = argv[i + 1]
      if (!value) throw new Error('--scope requires a value (p0, p1-p2, all)')
      options.scope = value
      i += 1
    } else if (arg.startsWith('--scope=')) {
      options.scope = arg.slice('--scope='.length)
    } else if (arg === '--workers') {
      const value = argv[i + 1]
      if (!value) throw new Error('--workers requires a value')
      options.workers = value
      i += 1
    } else if (arg.startsWith('--workers=')) {
      options.workers = arg.slice('--workers='.length)
    } else if (arg === '--skip-build') {
      options.skipBuild = true
    } else if (arg === '--list') {
      options.list = true
    } else if (arg === '--help' || arg === '-h') {
      options.help = true
    } else {
      throw new Error(`Unknown argument: ${arg}`)
    }
  }
  const validScopes = new Set(['p0', 'p1-p2', 'all'])
  if (!validScopes.has(options.scope)) {
    throw new Error(`Unknown scope ${options.scope}; expected one of p0, p1-p2, all`)
  }
  return options
}

function usage() {
  return [
    'Usage: node scripts/e2e-regression.mjs [options]',
    '',
    'Options:',
    '  --scope <p0|p1-p2|all>  Inventory priority scope (default: p1-p2)',
    '  --workers <n>           Playwright worker count',
    '  --list                  Resolve selection and list tests without running them',
    '  --skip-build            Reuse existing static/react build output',
    '  -h, --help              Show this help',
  ].join('\n')
}

function run(label, command, args, extraEnv = {}) {
  console.log(`\n> ${label}`)
  const result = spawnSync(command, args, {
    cwd: frontendRoot,
    stdio: 'inherit',
    env: { ...process.env, ...extraEnv },
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw Object.assign(new Error(`${label} failed with exit code ${result.status}`), {
      exitCode: result.status ?? 1,
    })
  }
}

export function main(argv) {
  const options = parseArgs(argv)
  if (options.help) {
    console.log(usage())
    return 0
  }

  const python = process.env.E2E_SELECTOR_PYTHON ?? 'python3'
  mkdirSync(path.dirname(defaultOutput), { recursive: true })

  run(
    `select inventory scope ${options.scope}`,
    python,
    [
      path.join(repositoryRoot, 'scripts', 'e2e_regression_select.py'),
      '--scope',
      options.scope,
      '--output',
      defaultOutput,
    ],
    { PYTHONPATH: repositoryRoot },
  )

  const configPath = path.join(frontendRoot, 'playwright.regression.config.ts')
  const env = {
    E2E_REGRESSION_SELECTION: defaultOutput,
    ...(options.workers ? { REGRESSION_WORKERS: options.workers } : {}),
  }

  if (options.list) {
    run('list selected regression tests', 'pnpm', [
      'exec',
      'playwright',
      'test',
      '--config',
      configPath,
      '--list',
    ], env)
    return 0
  }

  if (!options.skipBuild) {
    run('build frontend', 'pnpm', ['run', 'build'])
  }

  run('playwright regression', 'pnpm', ['exec', 'playwright', 'test', '--config', configPath], env)
  return 0
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.exitCode = main(process.argv.slice(2))
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
  }
}
