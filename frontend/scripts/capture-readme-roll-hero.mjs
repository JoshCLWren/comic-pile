#!/usr/bin/env node
/**
 * Capture the README hero image of the Roll page from the deterministic seeded
 * demo library. See `docs/images/README.md` for provenance.
 *
 * The capture is deliberately restricted to a local checkout so it can never
 * photograph a real production library:
 *
 *   make setup          # creates the seeded testuser/testpass123 library
 *   make dev            # API on :8000, Vite on :5173
 *   cd frontend && pnpm run capture:readme-roll
 *
 * Override `CHROMIUM_EXECUTABLE` when the Playwright-managed browser is not
 * installed (for example on a runner that only ships system Chromium).
 */

import { stat } from 'node:fs/promises'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const baseURL = process.env.ROLL_HERO_BASE_URL ?? 'http://127.0.0.1:5173'
const outputPath = resolve(repoRoot, process.env.ROLL_HERO_OUT ?? 'docs/images/roll-hero.png')
const username = process.env.ROLL_HERO_USERNAME ?? 'testuser'
const password = process.env.ROLL_HERO_PASSWORD ?? 'testpass123'
const maxBytes = 2 * 1024 * 1024

// The only series `scripts/seed_dev_db.py` creates. Anything else means the
// target account is not the seeded demo library, so the capture must stop.
const seededTitles = new Set(['Superman', 'Batman', 'Wonder Woman', 'The Flash', 'Aquaman'])

const loopbackHosts = new Set(['127.0.0.1', 'localhost', '::1', '[::1]'])

const target = new URL(baseURL)
if (!loopbackHosts.has(target.hostname)) {
  throw new Error(
    `Refusing to capture ${target.origin}: the Roll hero must come from a local seeded demo library, never a remote or production account.`,
  )
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
  args: ['--no-sandbox'],
})

try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 2,
  })

  const login = await page.request.post(new URL('/api/v1/auth/login', target).toString(), {
    data: { username, password },
  })
  if (!login.ok()) {
    throw new Error(
      `Seeded demo login failed (${login.status()}). Run \`make setup\` (or \`make seed-dev\`) first.`,
    )
  }
  const { access_token: accessToken } = await login.json()
  if (!accessToken) {
    throw new Error('Seeded demo login returned no access token.')
  }

  const bootstrapResponse = await page.request.get(
    new URL('/api/v2/roll/bootstrap', target).toString(),
    { headers: { Authorization: `Bearer ${accessToken}` } },
  )
  if (!bootstrapResponse.ok()) {
    throw new Error(`Roll bootstrap failed with ${bootstrapResponse.status()}.`)
  }
  const bootstrap = await bootstrapResponse.json()
  const poolTitles = (bootstrap.rollable ?? []).map((item) => item.thread.title)
  const unexpectedTitles = poolTitles.filter((title) => !seededTitles.has(title))
  if (poolTitles.length === 0 || unexpectedTitles.length > 0) {
    throw new Error(
      `Refusing to capture unseeded data. Expected only ${[...seededTitles].join(', ')}, saw ${poolTitles.join(', ') || 'an empty roll pool'}.`,
    )
  }

  await page.addInitScript((token) => {
    localStorage.setItem('auth_token', token)
  }, accessToken)

  await page.goto(target.toString(), { waitUntil: 'networkidle' })
  await page.getByTestId('roll-primary-action').waitFor({ state: 'visible' })
  await page.evaluate(() => document.fonts.ready)
  // Let the 3D die settle before capturing.
  await page.waitForTimeout(1500)

  await mkdir(dirname(outputPath), { recursive: true })
  await page.screenshot({ path: outputPath, fullPage: false })

  const { size } = await stat(outputPath)
  if (size > maxBytes) {
    throw new Error(`Captured ${outputPath} is ${size} bytes, above the 2 MiB README budget.`)
  }
  console.log(`Captured ${outputPath} (${size} bytes) from ${target.origin} as ${username}.`)
} finally {
  await browser.close()
}
