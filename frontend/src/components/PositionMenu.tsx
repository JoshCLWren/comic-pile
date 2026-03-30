import { useState, useEffect, useRef, useCallback } from 'react'
import type { Thread } from '../types'
import { usePositionMenu } from '../contexts/usePositionMenu'

interface PositionMenuProps {
  thread: Thread
  onMoveToFront: (threadId: number) => void
  onReposition: (thread: Thread) => void
  onMoveToBack: (threadId: number) => void
}

export default function PositionMenu({ thread, onMoveToFront, onReposition, onMoveToBack }: PositionMenuProps) {
  const { openThreadId, closeMenu: closeContextMenu, openMenu, toggleMenu } = usePositionMenu()
  const isOpen = openThreadId === thread.id

  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuItemsRef = useRef<(HTMLButtonElement | null)[]>([])
  const clickFromKeyboardRef = useRef(false)

  const closeMenu = useCallback(() => {
    closeContextMenu()
    triggerRef.current?.focus()
  }, [closeContextMenu])

  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeMenu()
        return
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault()
        const firstItem = menuItemsRef.current[0]
        if (document.activeElement === triggerRef.current) {
          firstItem?.focus()
        } else {
          const currentIndex = menuItemsRef.current.findIndex((item) => item === document.activeElement)
          const nextItem = menuItemsRef.current[currentIndex + 1]
          if (nextItem) {
            nextItem.focus()
          } else {
            firstItem?.focus()
          }
        }
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault()
        const items = menuItemsRef.current.filter(Boolean)
        const currentIndex = items.findIndex((item) => item === document.activeElement)
        const prevItem = items[currentIndex - 1]
        if (prevItem) {
          prevItem.focus()
        } else {
          triggerRef.current?.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, closeMenu])

  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeMenu()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, closeMenu])

  const handleTriggerClick = () => {
    if (clickFromKeyboardRef.current) {
      clickFromKeyboardRef.current = false
      return
    }
    toggleMenu(thread.id)
  }

  const handleTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
      e.preventDefault()
      clickFromKeyboardRef.current = true
      openMenu(thread.id)
      setTimeout(() => menuItemsRef.current[0]?.focus(), 0)
    }
  }

  const menuItems = [
    {
      label: 'Move to Front',
      icon: '\u2B06',
      action: () => {
        onMoveToFront(thread.id)
        closeMenu()
      },
    },
    {
      label: 'Reposition\u2026',
      icon: '\u2261',
      action: () => {
        onReposition(thread)
        closeMenu()
      },
    },
    {
      label: 'Move to Back',
      icon: '\u2193',
      action: () => {
        onMoveToBack(thread.id)
        closeMenu()
      },
    },
  ]

  return (
    <div className="relative" ref={menuRef}>
      <Tooltip content="More actions">
        <button
          ref={triggerRef}
          type="button"
          onClick={handleTriggerClick}
          onKeyDown={handleTriggerKeyDown}
          className="flex items-center justify-center w-11 h-11 text-stone-500 hover:text-white transition-colors text-lg rounded-lg hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
          aria-label="Position actions"
          aria-haspopup="menu"
          aria-expanded={isOpen}
        >
          &#x22EE;
        </button>
      </Tooltip>
      {isOpen && (
        <div
          className="absolute right-0 top-full mt-1 w-52 bg-[#1a1410]/95 border border-white/10 rounded-xl shadow-2xl z-50 py-1 overflow-hidden"
          role="menu"
          aria-label="Position actions"
        >
          {menuItems.map((item, index) => (
            <button
              key={item.label}
              ref={(el) => { menuItemsRef.current[index] = el }}
              type="button"
              onClick={item.action}
              className="w-full px-4 py-3 text-left text-sm text-stone-300 hover:bg-white/10 hover:text-white transition-colors flex items-center gap-3 focus:outline-none focus-visible:bg-white/10 focus-visible:text-white"
              role="menuitem"
            >
              <span className="text-base">{item.icon}</span>
              <span className="font-medium">{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Tooltip({ children, content }: { children: React.ReactNode; content: string }) {
  const [isVisible, setIsVisible] = useState(false)

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
      onFocus={() => setIsVisible(true)}
      onBlur={() => setIsVisible(false)}
    >
      {children}
      {isVisible && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 px-3 py-2 bg-[#1a1410]/95 text-stone-300 text-[10px] rounded-lg shadow-xl border border-white/10 z-[60] pointer-events-none">
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 rotate-45 w-2 h-2 bg-[#1a1410]/95 border-r border-b border-white/10"></div>
          {content}
        </div>
      )}
    </div>
  )
}
