import { createServer as createHttpServer, type Server } from 'node:http'
import { readFileSync, readdirSync } from 'node:fs'
import type { AddressInfo } from 'node:net'
import { resolve as resolvePath } from 'node:path'
import { createServer as createViteServer } from 'vite'
import { describe, expect, it } from 'vitest'
import { createApiDestinationResolver, createApiProxy } from '../../scripts/api-proxy'

const ingress = JSON.parse(readFileSync(resolvePath(process.cwd(), '../vercel.json'), 'utf8'))
const resolve = createApiDestinationResolver(ingress.routes)
const ipv4Loopback = [127, 0, 0, 1].join('.')

// vercel.json is bot-owned and regenerated post-merge, so at PR CI time it still
// carries Python exceptions for operations retired in this PR. Route fragments
// are the authoritative ingress source (see the migrated-preview test below),
// so resolve retired operations against those instead.
const fragmentsDir = resolvePath(process.cwd(), '../docs/api/route-fragments')
const fragmentRoutes = readdirSync(fragmentsDir)
  .filter((file) => file.endsWith('.json') && file !== 'vercel-rewrites.json')
  .flatMap((file) => {
    // SAFETY: route fragments are checked-in JSON objects whose `operations`,
    // when present, is an array of objects with method/src/dest string fields.
    const fragment = JSON.parse(readFileSync(resolvePath(fragmentsDir, file), 'utf8')) as {
      operations?: { method: string; src?: string; dest?: string }[]
    }
    return (fragment.operations ?? []).map((operation) => ({
      src: operation.src,
      methods: [operation.method],
      dest: operation.dest,
    }))
  })
const resolveRetired = createApiDestinationResolver(fragmentRoutes)

async function listen(server: Server): Promise<string> {
  await new Promise<void>((done) => server.listen(0, ipv4Loopback, done))
  // SAFETY: listen() bound a TCP port above, so address() returns AddressInfo, not a pipe name.
  const address = server.address() as AddressInfo
  if (!address) throw new Error('Missing test server port')
  return `http://${ipv4Loopback}:${address.port}`
}

async function close(server: Server) {
  server.closeAllConnections()
  await new Promise<void>((done, reject) => server.close((error) => error ? reject(error) : done()))
}

describe('development API routing', () => {
  it('sends every retired Python operation to native ingress', () => {
    const retired: { path: string; methods: string[] }[] = JSON.parse(readFileSync(
      resolvePath(process.cwd(), '../tests/fixtures/retired-python-handlers.json'), 'utf8',
    ))
    expect(retired.length).toBeGreaterThan(0)
    for (const operation of retired) {
      const path = operation.path.replace(/\{[^}]+\}/g, '42')
      for (const method of operation.methods) {
        expect(resolveRetired(method, path), `${method} ${path}`).toBe('native')
      }
    }
  })

  it('keeps Python exceptions, exact methods, queries and route ordering', () => {
    expect(resolve('GET', '/api/v2/reading-boundaries/42?context=queue')).toBe('native')
    expect(resolve('OPTIONS', '/api/v2/reading-boundaries/42')).toBe('native')
    expect(resolve('POST', '/api/v2/reading-boundaries')).toBe('native')
    expect(resolve('POST', '/api/v2/auth/login')).toBe('native')
    expect(resolve('GET', '/api/v1/catalog/series-mappings/preview')).toBe('native')
    expect(resolve('GET', '/api/v1/traffic-metrics')).toBe('native')
    expect(resolve('GET', '/api/not-a-route')).toBe('native')
    const ordered = createApiDestinationResolver([
      { src: '/api/mixed', methods: ['GET'], dest: '/api/index.py' },
      { src: '/api/mixed', methods: ['POST'], dest: '/api/native_roll.rs' },
      { src: '/api(?:/.*)?', dest: '/api/native_roll.rs' },
    ])
    expect(ordered('GET', '/api/mixed')).toBe('python')
    expect(ordered('POST', '/api/mixed')).toBe('native')
  })

  it('sends the migrated preview POST to native ingress in the route source of truth', () => {
    // vercel.json is bot-owned and regenerated post-merge, so at PR CI time it
    // still carries the Python exception for this POST. The route fragment is
    // the authoritative input that the regeneration workflow consumes (#5342).
    const catalog = JSON.parse(readFileSync(
      resolvePath(process.cwd(), '../docs/api/route-fragments/catalog.json'), 'utf8',
    ))
    const preview = catalog.operations.find((operation: { method: string; path: string }) =>
      operation.method === 'POST' &&
      operation.path === '/api/v1/catalog/series-mappings/preview')
    expect(preview).toBeDefined()
    expect(preview.dest).toBe('/api/native_roll.rs')
    expect(preview.runtime).toBe('native-rust')
  })

  it('forwards concurrent mixed-runtime requests with bodies and queries intact', async () => {
    const echo = (runtime: string) => createHttpServer(async (req, res) => {
      let body = ''
      for await (const chunk of req) body += chunk.toString()
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ runtime, method: req.method, url: req.url, body }))
    })
    const native = echo('native')
    const python = echo('python')
    const syntheticPythonRoute = {
      src: '^/api/v1/__mixed-runtime-proxy-fixture$',
      methods: ['POST', 'OPTIONS'],
      dest: '/api/index.py',
    }
    const routes = [syntheticPythonRoute, ...ingress.routes]
    const proxy = createApiProxy(routes, {
      native: await listen(native),
      python: await listen(python),
    })
    const vite = await createViteServer({
      configFile: false,
      server: { middlewareMode: true, proxy: { '/api': proxy }, watch: null },
      appType: 'custom',
    })
    const gateway = createHttpServer(vite.middlewares)
    try {
      const base = await listen(gateway)
      // One native route and one deterministic Python fixture. The fixture keeps
      // this mixed-runtime forwarding test independent of live Python route
      // migrations.
      const pythonPath = '/api/v1/__mixed-runtime-proxy-fixture'
      expect(createApiDestinationResolver(routes)('POST', pythonPath)).toBe('python')
      const results = await Promise.all(Array.from({ length: 12 }, async (_, index) => {
        const path = index % 2 === 0 ? '/api/v2/auth/login' : pythonPath
        const response = await fetch(`${base}${path}?request=${index}`, {
          method: 'POST', body: JSON.stringify({ request: index }),
          headers: { 'Content-Type': 'application/json' },
        })
        return response.json()
      }))
      results.forEach((result, index) => {
        expect(result).toEqual({
          runtime: index % 2 === 0 ? 'native' : 'python',
          method: 'POST',
          url: `${index % 2 === 0 ? '/api/v2/auth/login' : pythonPath}?request=${index}`,
          body: JSON.stringify({ request: index }),
        })
      })
    } finally {
      await close(gateway)
      await vite.close()
      await Promise.all([close(native), close(python)])
    }
  })
})
