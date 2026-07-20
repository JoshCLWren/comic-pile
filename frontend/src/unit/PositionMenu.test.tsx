import { act, render as baseRender, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import PositionMenu from '../components/PositionMenu'
import { PositionMenuProvider } from '../contexts/PositionMenuContext'

function render(ui: React.ReactElement) {
  return baseRender(<PositionMenuProvider>{ui}</PositionMenuProvider>)
}

const mockThread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  status: 'active' as const,
  queue_position: 1,
  issues_remaining: 5,
  collection_id: null,
  notes: null,
  total_issues: null,
  next_unread_issue_id: null,
  next_unread_issue_number: null,
  reading_progress: null,
  blocking_reasons: [],
  is_blocked: false,
  created_at: '2024-01-01T00:00:00Z',
}

describe('PositionMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(document.documentElement, 'clientWidth', {
      configurable: true,
      value: 1024,
    })
  })

  it('renders the overflow menu trigger button', () => {
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: /thread actions/i })).toBeInTheDocument()
  })

  it('opens the dropdown menu when the trigger button is clicked', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)

    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getAllByRole('menuitem')).toHaveLength(6)
  })

  it('renders the open menu in the document overlay layer', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    await user.click(screen.getByRole('button', { name: /thread actions/i }))

    expect(screen.getByRole('menu').parentElement).toBe(document.body)
  })

  it('repositions the portaled menu when the viewport changes', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      bottom: 100,
      right: 200,
    } as DOMRect)
    await user.click(trigger)

    const menu = screen.getByRole('menu')
    expect(menu).toHaveStyle({ top: '104px' })
    expect(menu).toHaveStyle({ right: '812px' })

    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      bottom: 160,
      right: 300,
    } as DOMRect)
    await act(async () => {
      window.dispatchEvent(new Event('resize'))
    })

    expect(menu).toHaveStyle({ top: '164px' })
    expect(menu).toHaveStyle({ right: '724px' })
  })

  it('clamps the menu to the right edge and flips it above a low trigger', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    const trigger = screen.getByRole('button', { name: /thread actions/i })
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      top: 700,
      bottom: 740,
      right: 1020,
    } as DOMRect)
    await user.click(trigger)

    const menu = screen.getByRole('menu')
    expect(menu).toHaveStyle({ top: '396px', right: '4px' })
  })

  it('shows Move to Front, Reposition, and Move to Back options', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)

    expect(screen.getByText('Move to Front')).toBeInTheDocument()
    expect(screen.getByText('Reposition\u2026')).toBeInTheDocument()
    expect(screen.getByText('Move to Back')).toBeInTheDocument()
  })

  it('calls onMoveToFront when Move to Front is clicked', async () => {
    const user = userEvent.setup()
    const onMoveToFront = vi.fn()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={onMoveToFront}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    await user.click(screen.getByText('Move to Front'))

    expect(onMoveToFront).toHaveBeenCalledWith(1)
  })

  it('calls onMoveToBack when Move to Back is clicked', async () => {
    const user = userEvent.setup()
    const onMoveToBack = vi.fn()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={onMoveToBack}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    await user.click(screen.getByText('Move to Back'))

    expect(onMoveToBack).toHaveBeenCalledWith(1)
  })

  it('calls onReposition when Reposition is clicked', async () => {
    const user = userEvent.setup()
    const onReposition = vi.fn()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={onReposition}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    await user.click(screen.getByText('Reposition\u2026'))

    expect(onReposition).toHaveBeenCalledWith(mockThread)
  })

  it('calls onEdit when Edit Thread is clicked', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={onEdit}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    await user.click(screen.getByText('Edit Thread'))

    expect(onEdit).toHaveBeenCalledWith(mockThread)
  })

  it('calls onDependencies when Dependencies is clicked', async () => {
    const user = userEvent.setup()
    const onDependencies = vi.fn()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={onDependencies}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    await user.click(screen.getByText('Dependencies'))

    expect(onDependencies).toHaveBeenCalledWith(mockThread)
  })

  it('calls onDelete when Delete Thread is clicked', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={onDelete}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    await user.click(screen.getByText('Delete Thread'))

    expect(onDelete).toHaveBeenCalledWith(1)
  })

  it('closes the menu after clicking a menu item', async () => {
    const user = userEvent.setup()
    const onMoveToFront = vi.fn()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={onMoveToFront}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await user.click(screen.getByText('Move to Front'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes the menu on Escape key press', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes the menu on outside click', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    await user.click(trigger)
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await user.click(document.body)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('has correct ARIA attributes on the trigger button', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')

    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('opens the menu when Enter is pressed on the trigger', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    trigger.focus()
    await user.keyboard('{Enter}')

    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('opens the menu when Space is pressed on the trigger', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    trigger.focus()
    await user.keyboard(' ')

    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('navigates menu items with arrow keys', async () => {
    const user = userEvent.setup()
    render(
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    )

    const trigger = screen.getByRole('button', { name: /thread actions/i })
    trigger.focus()
    await user.keyboard('{Enter}')

     const menuItems = screen.getAllByRole('menuitem')
     expect(document.activeElement).toBe(menuItems[0])
 
     await user.keyboard('{ArrowDown}')
     expect(document.activeElement).toBe(menuItems[1])
 
     await user.keyboard('{ArrowDown}')
     expect(document.activeElement).toBe(menuItems[2])
 
     await user.keyboard('{ArrowDown}')
     expect(document.activeElement).toBe(menuItems[3])
 
     await user.keyboard('{ArrowDown}')
     expect(document.activeElement).toBe(menuItems[4])
 
     await user.keyboard('{ArrowDown}')
     expect(document.activeElement).toBe(menuItems[5])
 
     await user.keyboard('{ArrowDown}')
     expect(document.activeElement).toBe(menuItems[0])
   })

   it('moves focus upward through portaled menu items and back to its trigger', async () => {
     const user = userEvent.setup()
     render(
       <PositionMenu
         thread={mockThread}
         onMoveToFront={vi.fn()}
         onReposition={vi.fn()}
         onMoveToBack={vi.fn()}
         onEdit={vi.fn()}
         onDependencies={vi.fn()}
         onDelete={vi.fn()}
       />
     )

     const trigger = screen.getByRole('button', { name: /thread actions/i })
     await user.click(trigger)
     const menuItems = screen.getAllByRole('menuitem')
     menuItems[1].focus()

     await user.keyboard('{ArrowUp}')
     expect(document.activeElement).toBe(menuItems[0])
     await user.keyboard('{ArrowUp}')
     expect(document.activeElement).toBe(trigger)
   })

   it('only one overflow menu can be open at a time', async () => {
     const user = userEvent.setup()
     const mockThread1 = {
       ...mockThread,
       id: 1,
       title: 'Thread 1',
     }
     const mockThread2 = {
       ...mockThread,
       id: 2,
       title: 'Thread 2',
     }

     render(
       <>
         <PositionMenu
           thread={mockThread1}
           onMoveToFront={vi.fn()}
           onReposition={vi.fn()}
            onMoveToBack={vi.fn()}
            onEdit={vi.fn()}
            onDependencies={vi.fn()}
            onDelete={vi.fn()}
          />
         <PositionMenu
           thread={mockThread2}
           onMoveToFront={vi.fn()}
           onReposition={vi.fn()}
            onMoveToBack={vi.fn()}
            onEdit={vi.fn()}
            onDependencies={vi.fn()}
            onDelete={vi.fn()}
          />
       </>
     )

     const triggers = screen.getAllByRole('button', { name: /thread actions/i })

     // Open first menu
     await user.click(triggers[0])
     expect(screen.getAllByRole('menu')).toHaveLength(1)
     expect(triggers[0]).toHaveAttribute('aria-expanded', 'true')
     expect(triggers[1]).toHaveAttribute('aria-expanded', 'false')

     // Open second menu - first should close automatically
     await user.click(triggers[1])
     expect(screen.getAllByRole('menu')).toHaveLength(1)
     expect(triggers[0]).toHaveAttribute('aria-expanded', 'false')
     expect(triggers[1]).toHaveAttribute('aria-expanded', 'true')

     // Click first again - second should close
     await user.click(triggers[0])
     expect(screen.getAllByRole('menu')).toHaveLength(1)
     expect(triggers[0]).toHaveAttribute('aria-expanded', 'true')
     expect(triggers[1]).toHaveAttribute('aria-expanded', 'false')
   })
 })
