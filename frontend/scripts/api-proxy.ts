import type { ProxyOptions } from 'vite'

export function createApiProxy(target: string): ProxyOptions {
  return {
    target,
    changeOrigin: true,
    secure: false,
    ws: true,
  }
}
