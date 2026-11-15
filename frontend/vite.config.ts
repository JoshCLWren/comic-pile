import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import sri from 'vite-plugin-sri'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { createApiProxy } from './scripts/api-proxy.ts'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function sitemapPlugin() {
  return {
    name: 'sitemap-generator',
    // Vite 8 can invoke closeBundle before writing index.html. Route SEO
    // generation consumes the built HTML, so wait for the writeBundle hook.
    writeBundle() {
      // Generate sitemap
      const sitemapScriptPath = path.resolve(__dirname, 'scripts', 'generate-sitemap.mjs')
      const sitemapResult = spawnSync('node', [sitemapScriptPath], {
        stdio: 'inherit',
        env: { ...process.env, NODE_ENV: 'production' },
      })
      if (sitemapResult.status !== 0) {
        throw new Error('Sitemap generation failed')
      }

      // Generate route-specific HTML files
      const htmlScriptPath = path.resolve(__dirname, 'scripts', 'generate-route-html.mjs')
      const htmlResult = spawnSync('node', [htmlScriptPath], {
        stdio: 'inherit',
        env: { ...process.env, NODE_ENV: 'production' },
      })
      if (htmlResult.status !== 0) {
        throw new Error('Route HTML generation failed')
      }
    },
  }
}

export default defineConfig(() => ({
  base: '/',
  plugins: [react(), sri({ algorithm: 'sha384' }), sitemapPlugin()],
  server: {
    host: '0.0.0.0',
    proxy: {
      // Match the deployed method/path split, including native v1 aliases and
      // the remaining Python exceptions. API version does not select runtime.
      '/api': createApiProxy(
        JSON.parse(readFileSync(path.resolve(__dirname, '../vercel.json'), 'utf8')).routes,
        {
          native: process.env.VITE_NATIVE_API_URL || 'http://localhost:8010',
          python: process.env.VITE_API_URL || 'http://localhost:8000',
        },
      ),
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
