import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const frontendRoot = path.resolve(import.meta.dirname, '../..')

describe('What’s new wiring', () => {
  it('keeps the authenticated route and More-menu link wired to the page', () => {
    const appSource = readFileSync(path.join(frontendRoot, 'src/App.tsx'), 'utf-8')
    const navigationSource = readFileSync(
      path.join(frontendRoot, 'src/components/Navigation.tsx'),
      'utf-8',
    )

    expect(appSource).toContain('path="/whats-new"')
    expect(appSource).toContain('<WhatsNewPage />')
    expect(navigationSource).toContain("path: '/whats-new'")
    expect(navigationSource).toContain('What\'s new')
  })

  it('reads the database-backed release API through the canonical releases query', () => {
    const pageSource = readFileSync(
      path.join(frontendRoot, 'src/pages/WhatsNewPage.tsx'),
      'utf-8',
    )
    const hookSource = readFileSync(
      path.join(frontendRoot, 'src/hooks/useReleases.ts'),
      'utf-8',
    )
    const queryKeysSource = readFileSync(
      path.join(frontendRoot, 'src/query/queryKeys.ts'),
      'utf-8',
    )
    const releaseApiSource = readFileSync(
      path.join(frontendRoot, 'src/services/api-releases.ts'),
      'utf-8',
    )
    const viteConfigSource = readFileSync(path.join(frontendRoot, 'vite.config.ts'), 'utf-8')

    expect(pageSource).toContain('useReleases')
    expect(pageSource).not.toContain('releasesApi.list')
    expect(hookSource).toContain('../services/api-releases')
    expect(hookSource).toContain('queryKeys.releases.list')
    expect(queryKeysSource).toContain('releases:')
    expect(releaseApiSource).toContain("'/v1/releases/'")
    expect(pageSource).not.toContain('/changelog.md')
    expect(viteConfigSource).not.toContain('changelogAsset')
    expect(viteConfigSource).not.toContain('docs/changelog')
  })
})
