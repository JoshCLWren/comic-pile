import type { ProxyOptions } from 'vite'

interface IngressRoute {
  src?: string
  methods?: readonly string[]
  dest?: string
}

/** Match API ingress in production order, including method-specific Python exceptions. */
export function createApiDestinationResolver(routes: readonly IngressRoute[]) {
  const rules = routes.flatMap((route) => {
    if (!route.src || !route.dest ||
      !['/api/native_roll.rs', '/api/native_issue.rs', '/api/index.py'].includes(route.dest)) {
      return []
    }
    return [{ ...route, pattern: new RegExp(`^(?:${route.src})$`) }]
  })

  return (method: string, url: string): 'native' | 'python' => {
    const pathname = url.split(/[?#]/, 1)[0]
    const rule = rules.find((candidate) =>
      (!candidate.methods || candidate.methods.includes(method.toUpperCase())) &&
      candidate.pattern.test(pathname),
    )
    return rule?.dest === '/api/index.py' ? 'python' : 'native'
  }
}

/** Route each request independently; never mutate shared proxy options in an async bypass. */
export function createApiProxy(
  routes: readonly IngressRoute[],
  targets: { native: string; python: string },
): ProxyOptions {
  const resolveDestination = createApiDestinationResolver(routes)
  const targetUrls = {
    native: new URL(targets.native),
    python: new URL(targets.python),
  }
  const selectTarget = (method: string, url: string) => {
    const target = targetUrls[resolveDestination(method, url)]
    return {
      protocol: target.protocol,
      hostname: target.hostname,
      host: target.host,
      port: Number(target.port || (target.protocol === 'https:' ? 443 : 80)),
      path: target.pathname === '/' ? undefined : target.pathname,
    }
  }

  return {
    target: targets.python,
    changeOrigin: true,
    secure: false,
    ws: true,
    configure(proxy) {
      // These passes receive request-local normalized options. Both HTTP and
      // WebSocket forwarding retain the original URL, query and request body.
      proxy.before('web', 'stream', (req, _res, options) => {
        options.target = selectTarget(req.method ?? 'GET', req.url ?? '/')
      })
      proxy.before('ws', 'stream', (req, _socket, options) => {
        options.target = selectTarget(req.method ?? 'GET', req.url ?? '/')
      })
    },
  }
}
