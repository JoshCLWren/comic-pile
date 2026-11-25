import { createServer as createHttpServer, type Server } from 'node:http'
import { createServer as createViteServer } from 'vite'
import { describe, expect, it } from 'vitest'
import { createApiProxy } from '../../scripts/api-proxy'

const ipv4Loopback = [127, 0, 0, 1].join('.')

async function listen(server: Server): Promise<string> {
  await new Promise<void>((done) => server.listen(0, ipv4Loopback, done))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Missing test server port')
  const { port } = address
  return `http://${ipv4Loopback}:${port}`
}

async function close(server: Server) {
  server.closeAllConnections()
  await new Promise<void>((done, reject) => server.close((error) => error ? reject(error) : done()))
}

describe('development API routing', () => {
  it('forwards concurrent v1 and v2 requests to native with their methods, queries and bodies intact', async () => {
    const native = createHttpServer(async (req, res) => {
      let body = ''
      for await (const chunk of req) body += chunk.toString()
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ method: req.method, url: req.url, body }))
    })
    const proxy = createApiProxy(await listen(native))
    const vite = await createViteServer({
      configFile: false,
      server: { middlewareMode: true, proxy: { '/api': proxy }, watch: null },
      appType: 'custom',
    })
    const gateway = createHttpServer(vite.middlewares)
    try {
      const base = await listen(gateway)
      const operations = [
        { path: '/api/v2/auth/login', method: 'POST' },
        { path: '/api/v1/catalog/series-mappings/preview', method: 'POST' },
        { path: '/api/v1/traffic-metrics', method: 'GET' },
        { path: '/api/not-a-route', method: 'GET' },
      ]
      const requests = operations.map(({ path, method }, index) => ({
        url: `${path}?request=${index}`,
        method,
        body: method === 'POST' ? JSON.stringify({ request: index }) : undefined,
      }))
      const results = await Promise.all(requests.map(async ({ url, method, body }) => {
        const response = await fetch(`${base}${url}`, {
          method,
          body,
          headers: { 'Content-Type': 'application/json' },
        })
        return response.json()
      }))
      expect(results).toEqual(requests.map((request) => ({ ...request, body: request.body ?? '' })))
    } finally {
      await close(gateway)
      await vite.close()
      await close(native)
    }
  })
})
