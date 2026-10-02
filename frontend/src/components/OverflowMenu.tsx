import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  // SAFETY: React's KeyboardEvent is a DOM event, not a React synthetic event
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import OverlayPortal from './OverlayPortal'

/**
 * Shared overflow ("⋯") menu primitive.
 *
 * Roll-style secondary actions are quiet affordances, not the local decision
 * area's primary workflow, so they collapse into a single low-emphasis trigger
 * instead of occupying the region under the page title. Menus must render
 * through `OverlayPortal layer="menu"` (see `frontend/AGENTS.md`), which also
 * keeps the surface out of the content region's stacking context.
 *
 * Behavior follows the menu-button pattern: the trigger owns
 * `aria-haspopup`/`aria-expanded`, the surface is a `role="menu"` of
 * `role="menuitem"` entries, Arrow/Home/End move between items, Escape closes
 * and returns focus to the trigger, and choosing an item restores focus to the
 * trigger so a dialog opened by that item returns focus here on close.
 */

export interface OverflowMenuItem {
  key: string
  label: string
  description?: string
  ariaLabel?: string
  disabled?: boolean
  onSelect: () => void
}

interface OverflowMenuProps {
  /** Accessible name for both the trigger and the menu surface. */
  label: string
  items: OverflowMenuItem[]
  triggerTestId?: string
  className?: string
}

const MENU_WIDTH_FALLBACK = 240
const MENU_HEIGHT_PER_ITEM = 44
const MENU_HEIGHT_PADDING = 8
const VIEWPORT_PADDING = 8
const MENU_OFFSET = 4

export default function OverflowMenu({
  label,
  items,
  triggerTestId,
  className,
}: OverflowMenuProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const menuId = useId()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const triggerContainerRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])
  const focusFirstItemRef = useRef(false)
  const itemCount = items.length

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return

    const rect = trigger.getBoundingClientRect()
    const menuRect = menuRef.current?.getBoundingClientRect()
    const menuWidth = menuRect?.width || MENU_WIDTH_FALLBACK
    const menuHeight =
      menuRect?.height || itemCount * MENU_HEIGHT_PER_ITEM + MENU_HEIGHT_PADDING
    const viewportWidth = document.documentElement.clientWidth
    const left = Math.min(
      Math.max(VIEWPORT_PADDING, rect.left),
      Math.max(VIEWPORT_PADDING, viewportWidth - menuWidth - VIEWPORT_PADDING),
    )
    const belowTop = rect.bottom + MENU_OFFSET
    const fitsBelow = belowTop + menuHeight <= window.innerHeight - VIEWPORT_PADDING
    const top = fitsBelow
      ? belowTop
      : Math.max(VIEWPORT_PADDING, rect.top - menuHeight - MENU_OFFSET)

    setPosition((current) =>
      current && current.top === top && current.left === left ? current : { top, left },
    )
  }, [itemCount])

  const closeMenu = useCallback((restoreFocus: boolean) => {
    setIsOpen(false)
    setPosition(null)
    if (restoreFocus) {
      triggerRef.current?.focus()
    }
  }, [])

  const openMenu = useCallback(
    (focusFirstItem: boolean) => {
      if (itemCount === 0) return
      itemRefs.current = []
      // Enter/Space arm the flag during keydown and open through the native
      // click, so a mouse-style open must not clear that intent.
      focusFirstItemRef.current = focusFirstItemRef.current || focusFirstItem
      setIsOpen(true)
    },
    [itemCount],
  )

  const focusItemAt = useCallback((index: number) => {
    const itemsList = itemRefs.current.filter((item): item is HTMLButtonElement => item != null)
    if (itemsList.length === 0) return
    const wrapped = (index + itemsList.length) % itemsList.length
    itemsList[wrapped]?.focus()
  }, [])

  // Opening needs a first pass with an estimated height so the surface never
  // paints in the wrong place before the measured position lands.
  useEffect(() => {
    if (!isOpen) return

    updatePosition()
    const frame = requestAnimationFrame(updatePosition)
    window.addEventListener('resize', updatePosition)
    document.addEventListener('scroll', updatePosition, true)

    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', updatePosition)
      document.removeEventListener('scroll', updatePosition, true)
    }
  }, [isOpen, updatePosition])

  useEffect(() => {
    if (!isOpen) return

    const handlePointerDownOutside = (event: MouseEvent) => {
      // SAFETY: click event targets are always DOM nodes, and Node.contains() requires a Node argument.
      const target = event.target as Node
      if (
        !menuRef.current?.contains(target) &&
        !triggerContainerRef.current?.contains(target)
      ) {
        closeMenu(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDownOutside)
    return () => document.removeEventListener('mousedown', handlePointerDownOutside)
  }, [isOpen, closeMenu])

  // The surface mounts through `OverlayPortal`, which only attaches its root
  // after the first commit, so item refs arrive one commit later than
  // `isOpen`. React attaches child refs before the parent's, so this ref
  // callback is the first point where keyboard activation can hand focus to an
  // item.
  const handleMenuRef = useCallback((element: HTMLDivElement | null) => {
    menuRef.current = element
    if (!element || !focusFirstItemRef.current) return
    focusFirstItemRef.current = false
    itemRefs.current.find((item): item is HTMLButtonElement => item != null)?.focus()
  }, [])

  const handleTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      openMenu(true)
      return
    }
    if (event.key === 'Escape' && isOpen) {
      event.preventDefault()
      closeMenu(false)
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      // Enter/Space already produce a native click on the trigger. Arming the
      // first-item focus here keeps keyboard activation inside the menu
      // without a second open path that could double-toggle.
      focusFirstItemRef.current = true
    }
  }

  const handleMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closeMenu(true)
      return
    }
    if (event.key === 'Tab') {
      closeMenu(false)
      return
    }

    const itemsList = itemRefs.current.filter((item): item is HTMLButtonElement => item != null)
    if (itemsList.length === 0) return
    // SAFETY: menu items are buttons, so activeElement must be a button when in menu
    const currentIndex = itemsList.indexOf(document.activeElement as HTMLButtonElement)

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusItemAt(currentIndex + 1)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      focusItemAt(currentIndex - 1)
      return
    }
    if (event.key === 'Home') {
      event.preventDefault()
      focusItemAt(0)
      return
    }
    if (event.key === 'End') {
      event.preventDefault()
      focusItemAt(itemsList.length - 1)
    }
  }

  const handleItemClick = (item: OverflowMenuItem) => {
    if (item.disabled) return
    // Run the action first so a dialog it opens captures the trigger as the
    // element to restore focus to, then collapse the menu.
    item.onSelect()
    closeMenu(true)
  }

  return (
    <div className={`relative shrink-0 ${className ?? ''}`} ref={triggerContainerRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => (isOpen ? closeMenu(false) : openMenu(false))}
        onKeyDown={handleTriggerKeyDown}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        data-testid={triggerTestId}
        className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-lg leading-none text-[var(--theme-text-dim)] transition-colors hover:bg-[var(--theme-bg-panel)] hover:text-[var(--theme-text-primary)] focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
      >
        <span aria-hidden="true">&#x22EF;</span>
      </button>
      {isOpen && (
        <OverlayPortal layer="menu">
          <div
            ref={handleMenuRef}
            id={menuId}
            role="menu"
            aria-label={label}
            onKeyDown={handleMenuKeyDown}
            className="surface-glass fixed min-w-[13rem] max-w-[min(20rem,calc(100vw-1rem))] p-1 shadow-xl"
            style={position ?? { top: 0, left: 0, visibility: 'hidden' }}
          >
            {items.map((item, index) => (
              <button
                key={item.key}
                ref={(element) => {
                  itemRefs.current[index] = element
                }}
                type="button"
                role="menuitem"
                onClick={() => handleItemClick(item)}
                aria-label={item.ariaLabel}
                aria-disabled={item.disabled ? true : undefined}
                className={`flex min-h-11 w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left transition-colors focus:outline-none focus-visible:bg-white/10 ${
                  item.disabled
                    ? 'cursor-not-allowed text-[var(--theme-text-dim)]'
                    : 'text-[var(--theme-text-primary)] hover:bg-white/10 focus-visible:bg-white/10'
                }`}
              >
                <span className="text-xs font-black uppercase tracking-wider">
                  {item.label}
                </span>
                {item.description ? (
                  <span className="text-[11px] font-normal leading-snug text-[var(--theme-text-muted)]">
                    {item.description}
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        </OverlayPortal>
      )}
    </div>
  )
}