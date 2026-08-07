import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const frontendRoot = path.resolve(import.meta.dirname, '../..')

describe('What’s New wiring', () => {
  it('keeps the authenticated route and More-menu link wired to the page', () => {
    const appSource = readFileSync(path.join(frontendRoot, 'src/App.tsx'), 'utf-8')
    const navigationSource = readFileSync(
      path.join(frontendRoot, 'src/components/Navigation.tsx'),
      'utf-8',
    )

    expect(appSource).toContain('path="/whats-new"')
    expect(appSource).toContain('<WhatsNewPage />')
    expect(navigationSource).toContain('to="/whats-new"')
    expect(navigationSource).toContain('What’s New')
  })

  it('keeps the archive and fragments wired to the production static asset', () => {
    const viteConfigSource = readFileSync(path.join(frontendRoot, 'vite.config.ts'), 'utf-8')
    const changelogSource = readFileSync(
      path.resolve(frontendRoot, '../docs/changelog.md'),
      'utf-8',
    )

    expect(changelogSource).toMatch(/^# Changelog/m)
    expect(viteConfigSource).toContain("const defaultArchivePath = path.resolve(__dirname, '../docs/changelog.md')")
    expect(viteConfigSource).toContain("const defaultFragmentsDir = path.resolve(__dirname, '../docs/changelog.d')")
    expect(viteConfigSource).toContain("fileName: 'changelog.md'")
    expect(viteConfigSource).toContain('source: renderChangelog(options)')
  })
})
