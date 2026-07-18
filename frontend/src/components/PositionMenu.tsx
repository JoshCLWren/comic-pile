import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import type { Thread } from '../types'
import { usePositionMenu } from '../contexts/usePositionMenu'

interface PositionMenuProps {
  thread: Thread
  onMoveToFront: (threadId: number) => void
  onReposition: (thread: Thread) => void
  onMoveToBack: (threadId: number) => void
  onEdit: (thread: Thread) => void
  onDependencies: (thread: Thread) => void
  onDelete: (threadId: number) => void
}

export default function PositionMenu({ thread, onMoveToFront, onReposition, onMoveToBack, onEdit, onDependencies, onDelete }: PositionMenuProps) {
  const { openThreadId, closeMenu: closeContextMenu, openMenu, toggleMenu } = usePositionMenu()
  const isOpen = openThreadId === thread.id

  const triggerRef = useRef<HTMLButtonElement>(null)
  const triggerContainerRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuItemsRef = useRef<(HTMLButtonElement | null)[]>([])
  const clickFromKeyboardRef = useRef(false)
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null)

  const updateMenuPosition = useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return

    const rect = trigger.getBoundingClientRect()
    setMenuPosition({
      top: rect.bottom + 4,
      right: window.innerWidth - rect.right,
    })
  }, [])

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

    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    document.addEventListener('scroll', updateMenuPosition, true)

    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      document.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [isOpen, updateMenuPosition])

  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        !menuRef.current?.contains(target) &&
        !triggerContainerRef.current?.contains(target)
      ) {
        closeMenu()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, closeMenu])

  const handleTriggerClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    if (clickFromKeyboardRef.current) {
      clickFromKeyboardRef.current = false
      return
    }
    toggleMenu(thread.id)
  }

  const handleTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
      e.preventDefault()
      e.stopPropagation()
      clickFromKeyboardRef.current = true
      openMenu(thread.id)
      setTimeout(() => menuItemsRef.current[0]?.focus(), 0)
    }
  }

  const menuItems: Array<{
    label: string
    icon: string
    ariaLabel: string
    destructive?: boolean
    action: () => void
  }> = [
    {
      label: 'Move to Front',
      icon: '\u2B06',
      ariaLabel: 'Move to front',
      action: () => {
        onMoveToFront(thread.id)
        closeMenu()
      },
    },
    {
      label: 'Reposition\u2026',
      icon: '\u2261',
      ariaLabel: 'Reposition thread',
      action: () => {
        onReposition(thread)
        closeMenu()
      },
    },
    {
      label: 'Move to Back',
      icon: '\u2193',
      ariaLabel: 'Move to back',
      action: () => {
        onMoveToBack(thread.id)
        closeMenu()
      },
    },
    {
      label: 'Edit Thread',
      icon: '\u270F\uFE0F',
      ariaLabel: 'Edit thread',
      action: () => {
        onEdit(thread)
        closeMenu()
      },
    },
    {
      label: 'Dependencies',
      icon: '\u26D3\uFE0E',
      ariaLabel: 'Manage dependencies',
      action: () => {
        onDependencies(thread)
        closeMenu()
      },
    },
    {
      label: 'Delete Thread',
      icon: '\u{1F5D1}',
      ariaLabel: 'Delete thread',
      destructive: true,
      action: () => {
        onDelete(thread.id)
        closeMenu()
      },
    },
  ]

  return (
    <div className="relative" ref={triggerContainerRef}>
      <button
        ref={triggerRef}
        type="button"
        onClick={handleTriggerClick}
        onKeyDown={handleTriggerKeyDown}
        className="flex items-center justify-center w-11 h-11 text-stone-500 hover:text-white transition-colors text-lg rounded-lg hover:bg-white/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
        aria-label="Thread actions"
        aria-haspopup="menu"
        aria-expanded={isOpen}
      >
        &#x22EE;
      </button>
      {isOpen && menuPosition && createPortal(
        <div
          ref={menuRef}
          className="fixed w-52 bg-[#1a1410]/95 border border-white/10 rounded-xl shadow-2xl z-[1000] py-1 overflow-hidden"
          style={menuPosition}
          role="menu"
          aria-label="Thread actions"
        >
          {menuItems.map((item, index) => (
            <button
              key={item.label}
              ref={(el) => { menuItemsRef.current[index] = el }}
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                item.action()
              }}
              aria-label={item.ariaLabel}
              className={`w-full px-4 py-3 text-left text-sm transition-colors flex items-center gap-3 focus:outline-none focus-visible:bg-white/10 ${
                item.destructive
                  ? 'text-red-400 hover:bg-red-500/10 hover:text-red-300 focus-visible:bg-red-500/10 focus-visible:text-red-300'
                  : 'text-stone-300 hover:bg-white/10 hover:text-white focus-visible:bg-white/10 focus-visible:text-white'
              }`}
              role="menuitem"
            >
              <span className="text-base">{item.icon}</span>
              <span className="font-medium">{item.label}</span>
            </button>
          ))}
        </div>,
        document.body,
      )}
    </div>
  )
}
