/**
 * The ComicPile page scroller is `#root`, not the window.
 *
 * `html`/`body` are `overflow: hidden` (see `frontend/src/styles.css`) so
 * overscroll and iOS modal bleed stay contained. `#root` owns `overflow-y: auto`
 * and is the element `Modal` locks. Window-virtualizer helpers that read
 * `window.scrollY` therefore stay at 0 while the user scrolls the real page,
 * which leaves later virtual rows unmounted and paints a giant blank spacer
 * (issue #2725).
 */

import type { Virtualizer } from '@tanstack/react-virtual'

type ObserveAppScrollOffset = (
  instance: Virtualizer<Window, Element>,
  cb: (offset: number, isScrolling: boolean) => void,
) => void | (() => void)

type ScrollAppToOffset = (
  offset: number,
  options: { adjustments?: number; behavior?: ScrollBehavior },
  instance: Virtualizer<Window, Element>,
) => void

/** DOM id of the application page scroller. */
export const APP_SCROLL_ELEMENT_ID = 'root'

/**
 * The element that actually owns page scrolling, or `null` when it is not in
 * the document (jsdom unit tests without the production shell).
 */
export function getAppScrollElement(): HTMLElement | null {
  if (typeof document === 'undefined') {
    return null
  }
  return document.getElementById(APP_SCROLL_ELEMENT_ID)
}

/**
 * Current vertical offset of the page scroller.
 *
 * Prefers `#root.scrollTop`. Falls back to `window.scrollY` when the app
 * scroller is absent so layout-less unit tests keep the historical window
 * offset of 0.
 */
export function readAppScrollOffset(): number {
  const root = getAppScrollElement()
  if (root) {
    return root.scrollTop
  }
  return typeof window === 'undefined' ? 0 : window.scrollY
}

/**
 * Document-space distance from the start of the page scroller's content to
 * `wrapper`. Stable across scroll: viewport-relative `top` plus the scroller's
 * `scrollTop` cancel the current offset, unlike `rect.top + window.scrollY`
 * which collapses to a viewport-relative value while `#root` is scrolled.
 *
 * @param wrapper - The virtualized list's offset parent.
 * @returns Pixel margin the virtualizer should add to item `start` values.
 */
export function measureAppScrollMargin(wrapper: HTMLElement): number {
  const wrapperRect = wrapper.getBoundingClientRect()
  const scrollElement = getAppScrollElement()
  if (!scrollElement) {
    return wrapperRect.top + (typeof window === 'undefined' ? 0 : window.scrollY)
  }
  const scrollRect = scrollElement.getBoundingClientRect()
  return wrapperRect.top - scrollRect.top + scrollElement.scrollTop
}

/**
 * Subscribe to the page scroller's vertical offset for `@tanstack/react-virtual`.
 *
 * Matches the `observeElementOffset` contract used by `useWindowVirtualizer`:
 * call `cb` with the current offset, then again on every `scroll` event.
 * Listens on `#root` when present so Queue virtualization tracks the element
 * the user actually scrolls.
 *
 * @param _instance - Virtualizer instance; unused because Queue is vertical.
 * @param cb - Offset consumer supplied by the virtualizer.
 * @returns Unsubscribe function.
 */
export const observeAppScrollOffset: ObserveAppScrollOffset = (_instance, cb) => {
  const root = getAppScrollElement()
  const target: EventTarget = root ?? window
  const onScroll = () => {
    cb(readAppScrollOffset(), true)
  }
  target.addEventListener('scroll', onScroll, { passive: true })
  cb(readAppScrollOffset(), false)
  return () => {
    target.removeEventListener('scroll', onScroll)
  }
}

/**
 * Scroll-to helper for the page scroller. Used by the Queue virtualizer's
 * drag-edge auto-scroll. Writes `#root.scrollTop` only so route restoration
 * stays owned by `scrollCoordinator` (issue #2582).
 *
 * @param offset - Target content offset in pixels.
 * @param options - Virtualizer scroll options; `adjustments` is added to offset.
 */
export const scrollAppToOffset: ScrollAppToOffset = (offset, options) => {
  const root = getAppScrollElement()
  if (!root) {
    return
  }
  root.scrollTo({
    top: offset + (options.adjustments ?? 0),
    behavior: options.behavior,
  })
}
