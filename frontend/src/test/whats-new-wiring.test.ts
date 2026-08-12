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

  it('reads the database-backed release API without a static changelog build dependency', () => {
    const pageSource = readFileSync(
      path.join(frontendRoot, 'src/pages/WhatsNewPage.tsx'),
      'utf-8',
    )
    const releaseApiSource = readFileSync(
      path.join(frontendRoot, 'src/services/api-releases.ts'),
      'utf-8',
    )
    const viteConfigSource = readFileSync(path.join(frontendRoot, 'vite.config.ts'), 'utf-8')

    expect(pageSource).toContain('releasesApi.list')
    expect(releaseApiSource).toContain("'/v1/releases/'")
    expect(pageSource).not.toContain('/changelog.md')
    expect(viteConfigSource).not.toContain('changelogAsset')
    expect(viteConfigSource).not.toContain('docs/changelog')
  })
})
