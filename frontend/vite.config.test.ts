import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { changelogAsset, renderChangelog } from './vite.config'

const temporaryDirectories: string[] = []

function createFixture(
  fragments: Record<string, string>,
  archive = '# Changelog\n\n## 2026-08-05\n\n**Archive**\n\n- Older change.\n',
) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'comic-pile-changelog-'))
  temporaryDirectories.push(root)
  const archivePath = path.join(root, 'changelog.md')
  const fragmentsDir = path.join(root, 'changelog.d')
  mkdirSync(fragmentsDir)
  writeFileSync(archivePath, archive)
  for (const [fileName, content] of Object.entries(fragments)) {
    writeFileSync(path.join(fragmentsDir, fileName), content)
  }
  writeFileSync(path.join(fragmentsDir, 'README.md'), 'Instructions only.')
  return { archivePath, fragmentsDir }
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true })
  }
})

describe('renderChangelog', () => {
  it('assembles isolated fragments newest-first before the frozen archive', () => {
    const paths = createFixture({
      '2026-08-06-882.md':
        '## 2026-08-06\n\n**Factory reliability**\n\n- Added fragments ([#882](https://github.com/JoshCLWren/comic-pile/pull/882)).\n',
      '2026-08-07-900.md':
        '## 2026-08-07\n\n**Queue**\n\n- Newer change ([#900](https://github.com/JoshCLWren/comic-pile/pull/900)).\n',
      '2026-08-07-899.md':
        '## 2026-08-07\n\n**Roll**\n\n- Earlier change ([#899](https://github.com/JoshCLWren/comic-pile/pull/899)).\n',
    })

    const rendered = renderChangelog(paths)

    expect(rendered).toContain(readFileSync(paths.archivePath, 'utf-8').replace('# Changelog\n\n', '').trim())
    expect(rendered.indexOf('Newer change')).toBeLessThan(rendered.indexOf('Earlier change'))
    expect(rendered.indexOf('Earlier change')).toBeLessThan(rendered.indexOf('Added fragments'))
    expect(rendered.indexOf('Added fragments')).toBeLessThan(rendered.indexOf('Older change'))
  })

  it('rejects malformed filenames', () => {
    const paths = createFixture({
      'release-note.md':
        '## 2026-08-06\n\n**Factory reliability**\n\n- Bad filename ([#882](https://github.com/JoshCLWren/comic-pile/pull/882)).\n',
    })

    expect(() => renderChangelog(paths)).toThrow('expected YYYY-MM-DD-<pr>.md')
  })

  it('rejects duplicate PR fragments even across dates', () => {
    const paths = createFixture({
      '2026-08-06-882.md':
        '## 2026-08-06\n\n**Factory reliability**\n\n- First ([#882](https://github.com/JoshCLWren/comic-pile/pull/882)).\n',
      '2026-08-07-882.md':
        '## 2026-08-07\n\n**Factory reliability**\n\n- Duplicate ([#882](https://github.com/JoshCLWren/comic-pile/pull/882)).\n',
    })

    expect(() => renderChangelog(paths)).toThrow('Duplicate changelog fragment for PR #882')
  })

  it('requires the filename date and PR link to match the fragment', () => {
    const paths = createFixture({
      '2026-08-06-882.md':
        '## 2026-08-05\n\n**Factory reliability**\n\n- Wrong metadata ([#881](https://github.com/JoshCLWren/comic-pile/pull/881)).\n',
    })

    expect(() => renderChangelog(paths)).toThrow('must start with ## 2026-08-06')
  })
})

describe('changelogAsset', () => {
  it('emits the assembled changelog into the production bundle', () => {
    const paths = createFixture({
      '2026-08-06-882.md':
        '## 2026-08-06\n\n**Factory reliability**\n\n- Added fragments ([#882](https://github.com/JoshCLWren/comic-pile/pull/882)).\n',
    })
    const plugin = changelogAsset(paths)
    const emitFile = vi.fn()

    plugin.generateBundle?.call({ emitFile } as never, {} as never, {} as never, false)

    expect(emitFile).toHaveBeenCalledWith({
      type: 'asset',
      fileName: 'changelog.md',
      source: renderChangelog(paths),
    })
  })

  it('serves the same assembled changelog during local development', () => {
    const paths = createFixture({
      '2026-08-06-882.md':
        '## 2026-08-06\n\n**Factory reliability**\n\n- Added fragments ([#882](https://github.com/JoshCLWren/comic-pile/pull/882)).\n',
    })
    let middleware:
      | ((
          request: unknown,
          response: {
            statusCode: number
            setHeader: ReturnType<typeof vi.fn>
            end: ReturnType<typeof vi.fn>
          },
        ) => void)
      | undefined
    const use = vi.fn((_route: string, handler: typeof middleware) => {
      middleware = handler
    })
    const plugin = changelogAsset(paths)

    plugin.configureServer?.({ middlewares: { use } } as never)

    expect(use).toHaveBeenCalledWith('/changelog.md', expect.any(Function))

    const response = {
      statusCode: 0,
      setHeader: vi.fn(),
      end: vi.fn(),
    }
    middleware?.({}, response)

    expect(response.statusCode).toBe(200)
    expect(response.setHeader).toHaveBeenCalledWith('Content-Type', 'text/markdown; charset=utf-8')
    expect(response.end).toHaveBeenCalledWith(renderChangelog(paths))
  })
})
