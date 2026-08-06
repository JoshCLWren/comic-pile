import { readFileSync, readdirSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import sri from 'vite-plugin-sri'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const defaultArchivePath = path.resolve(__dirname, '../docs/changelog.md')
const defaultFragmentsDir = path.resolve(__dirname, '../docs/changelog.d')
const fragmentPattern = /^(\d{4}-\d{2}-\d{2})-(\d+)\.md$/

interface ChangelogAssetOptions {
  archivePath?: string
  fragmentsDir?: string
}

interface ChangelogFragment {
  date: string
  prNumber: number
  content: string
  fileName: string
}

function readFragments(fragmentsDir: string): ChangelogFragment[] {
  const fragments: ChangelogFragment[] = []
  const seenPrNumbers = new Set<number>()

  for (const entry of readdirSync(fragmentsDir, { withFileTypes: true })) {
    if (!entry.isFile() || entry.name === 'README.md') continue

    const match = fragmentPattern.exec(entry.name)
    if (!match) {
      throw new Error(
        `Invalid changelog fragment filename ${entry.name}; expected YYYY-MM-DD-<pr>.md`,
      )
    }

    const [, date, rawPrNumber] = match
    const prNumber = Number(rawPrNumber)
    if (seenPrNumbers.has(prNumber)) {
      throw new Error(`Duplicate changelog fragment for PR #${prNumber}`)
    }
    seenPrNumbers.add(prNumber)

    const content = readFileSync(path.join(fragmentsDir, entry.name), 'utf-8').trim()
    const expectedHeading = `## ${date}`
    const expectedLink = `[#${prNumber}](https://github.com/JoshCLWren/comic-pile/pull/${prNumber})`

    if (!content.startsWith(`${expectedHeading}\n`)) {
      throw new Error(`${entry.name} must start with ${expectedHeading}`)
    }
    if (!content.includes(expectedLink)) {
      throw new Error(`${entry.name} must link ${expectedLink}`)
    }

    fragments.push({ date, prNumber, content, fileName: entry.name })
  }

  return fragments.sort(
    (left, right) =>
      right.date.localeCompare(left.date) ||
      right.prNumber - left.prNumber ||
      right.fileName.localeCompare(left.fileName),
  )
}

export function renderChangelog(options: ChangelogAssetOptions = {}): string {
  const archivePath = options.archivePath ?? defaultArchivePath
  const fragmentsDir = options.fragmentsDir ?? defaultFragmentsDir
  const archive = readFileSync(archivePath, 'utf-8').trim()

  if (!archive.startsWith('# Changelog')) {
    throw new Error(`${archivePath} must start with # Changelog`)
  }

  const archiveBody = archive.replace(/^# Changelog\s*/, '').trim()
  const fragmentBodies = readFragments(fragmentsDir).map(fragment => fragment.content)
  const sections = ['# Changelog', ...fragmentBodies]
  if (archiveBody) sections.push(archiveBody)

  return `${sections.join('\n\n')}\n`
}

export function changelogAsset(options: ChangelogAssetOptions = {}): Plugin {
  return {
    name: 'comic-pile-changelog-asset',
    configureServer(server) {
      server.middlewares.use('/changelog.md', (_request, response) => {
        response.statusCode = 200
        response.setHeader('Content-Type', 'text/markdown; charset=utf-8')
        response.end(renderChangelog(options))
      })
    },
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'changelog.md',
        source: renderChangelog(options),
      })
    },
  }
}

export default defineConfig(() => ({
  base: '/',
  plugins: [react(), changelogAsset(), sri({ algorithm: 'sha384' })],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        ws: true,
        configure: (proxy, _options) => {
          proxy.on('error', (err, _req, _res) => {
            console.log('proxy error', err)
          })
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            console.log('Sending Request to the Target:', req.method, req.url)
          })
          proxy.on('proxyRes', (proxyRes, req, _res) => {
            console.log('Received Response from the Target:', proxyRes.statusCode, req.url)
          })
        },
      },
    },
  },
  build: {
    outDir: '../static/react',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('three')) return 'three'
          if (id.includes('node_modules')) return 'vendor'
          return undefined
        },
      },
    },
    chunkSizeWarningLimit: 550,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
}))
