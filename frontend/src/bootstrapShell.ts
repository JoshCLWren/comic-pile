const READY_SELECTOR = '[data-app-shell-ready]'
const RECONNECTING_DELAY_MS = 8_000
const FAILSAFE_MAX_DELAY_MS = 30_000

export interface BootstrapShellLifecycle {
  disconnect: () => void
}

export function startBootstrapShellLifecycle(
  rootElement: HTMLElement,
  shellElement: HTMLElement | null,
  reconnectingDelayMs = RECONNECTING_DELAY_MS,
  failsafeMaxDelayMs = FAILSAFE_MAX_DELAY_MS,
): BootstrapShellLifecycle {
  if (!shellElement) {
    return { disconnect: () => undefined }
  }

  const statusElement = shellElement.querySelector<HTMLElement>('[data-bootstrap-status]')
  const removeShellWhenReady = () => {
    if (!rootElement.querySelector(READY_SELECTOR)) {
      return false
    }

    shellElement.remove()
    return true
  }

  if (removeShellWhenReady()) {
    return { disconnect: () => undefined }
  }

  const observer = new MutationObserver(() => {
    if (removeShellWhenReady()) {
      observer.disconnect()
      window.clearTimeout(reconnectingTimer)
      window.clearTimeout(failsafeTimer)
    }
  })

  const reconnectingTimer = window.setTimeout(() => {
    if (statusElement && shellElement.isConnected) {
      statusElement.textContent = 'Still waking ComicPile. Your library is safe while services reconnect.'
      statusElement.dataset.state = 'reconnecting'
    }
  }, reconnectingDelayMs)

  const failsafeTimer = window.setTimeout(() => {
    if (shellElement.isConnected) {
      shellElement.remove()
    }
    observer.disconnect()
    window.clearTimeout(reconnectingTimer)
  }, failsafeMaxDelayMs)

  observer.observe(rootElement, { childList: true, subtree: true })

  return {
    disconnect: () => {
      observer.disconnect()
      window.clearTimeout(reconnectingTimer)
      window.clearTimeout(failsafeTimer)
    },
  }
}
