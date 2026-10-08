const READY_SELECTOR = '[data-app-shell-ready]'
const SLOW_STATUS_DELAY_MS = 8_000
const FAILSAFE_MAX_DELAY_MS = 30_000

export interface BootstrapShellLifecycle {
  disconnect: () => void
}

export function startBootstrapShellLifecycle(
  rootElement: HTMLElement,
  shellElement: HTMLElement | null,
  slowStatusDelayMs = SLOW_STATUS_DELAY_MS,
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
      window.clearTimeout(slowStatusTimer)
      window.clearTimeout(failsafeTimer)
    }
  })

  const slowStatusTimer = window.setTimeout(() => {
    if (statusElement && shellElement.isConnected) {
      statusElement.textContent =
        'Still loading ComicPile. This is taking longer than usual. Your library is safe.'
      statusElement.dataset.state = 'slow'
    }
  }, slowStatusDelayMs)

  const failsafeTimer = window.setTimeout(() => {
    if (shellElement.isConnected) {
      shellElement.remove()
    }
    observer.disconnect()
    window.clearTimeout(slowStatusTimer)
  }, failsafeMaxDelayMs)

  observer.observe(rootElement, { childList: true, subtree: true })

  return {
    disconnect: () => {
      observer.disconnect()
      window.clearTimeout(slowStatusTimer)
      window.clearTimeout(failsafeTimer)
    },
  }
}
