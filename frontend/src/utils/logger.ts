/**
 * Client-side logging that sends to backend for terminal output
 */
export function logToServer(level: 'info' | 'warn' | 'error', message: string, data?: unknown) {
  fetch('/api/debug/log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level, message, data }),
  }).catch(() => {
  })
}
