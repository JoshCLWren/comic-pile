import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { changelogAsset } from './vite.config'

const changelogPath = path.resolve(import.meta.dirname, '../docs/changelog.md')

describe('changelogAsset', () => {
  it('emits the canonical changelog into the production bundle', () => {
    const plugin = changelogAsset()
    const emitFile = vi.fn()

    plugin.generateBundle?.call({ emitFile } as never, {} as never, {} as never, false)

    expect(emitFile).toHaveBeenCalledWith({
      type: 'asset',
      fileName: 'changelog.md',
      source: readFileSync(changelogPath, 'utf-8'),
    })
  })

  it('serves the same canonical changelog during local development', () => {
    let middleware: ((request: unknown, response: { statusCode: number; setHeader: ReturnType<typeof vi.fn>; end: ReturnType<typeof vi.fn> }) => void) | undefined
    const use = vi.fn((_route: string, handler: typeof middleware) => {
      middleware = handler
    })
    const plugin = changelogAsset()

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
    expect(response.end).toHaveBeenCalledWith(readFileSync(changelogPath, 'utf-8'))
  })
})
