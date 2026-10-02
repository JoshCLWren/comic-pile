import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import OverflowMenu from '../components/OverflowMenu'

function makeItems() {
  return [
    { key: 'a', label: 'First', onSelect: vi.fn() },
    { key: 'b', label: 'Second', description: 'Secondary detail', onSelect: vi.fn() },
    { key: 'c', label: 'Third', disabled: true, onSelect: vi.fn() },
  ]
}

function stubTriggerRect(
  trigger: HTMLElement,
  rect: { left: number; right: number; top: number; bottom: number },
) {
  // SAFETY: the literal below is built from the caller's rect plus the derived
  // width/height/x/y and a no-op toJSON, which is the full DOMRect surface.
  vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
    ...rect,
    width: rect.right - rect.left,
    height: rect.bottom - rect.top,
    x: rect.left,
    y: rect.top,
    toJSON() {},
  } as DOMRect)
}

async function openMenu(): Promise<HTMLElement> {
  const trigger = screen.getByRole('button', { name: 'Comic corrections' })
  fireEvent.click(trigger)
  return screen.findByRole('menu')
}

describe('OverflowMenu', () => {
  it('renders the surface in the shared menu overlay layer', async () => {
    render(<OverflowMenu label="Comic corrections" items={makeItems()} />)

    await openMenu()

    const menu = screen.getByRole('menu')
    const menuRoot = document.getElementById('comic-pile-overlay-root')
    expect(menuRoot).not.toBeNull()
    expect(menuRoot?.contains(menu)).toBe(true)
  })

  it('exposes every item as a menuitem with its description', async () => {
    render(<OverflowMenu label="Comic corrections" items={makeItems()} />)

    const menu = await openMenu()

    expect(within(menu).getAllByRole('menuitem')).toHaveLength(3)
    expect(within(menu).getByRole('menuitem', { name: /Second/ })).toHaveTextContent(
      'Secondary detail',
    )
  })

  it('marks aria-disabled items instead of removing them from the menu', async () => {
    const items = makeItems()
    render(<OverflowMenu label="Comic corrections" items={items} />)

    const menu = await openMenu()
    const disabledItem = within(menu).getByRole('menuitem', { name: 'Third' })
    expect(disabledItem).toHaveAttribute('aria-disabled', 'true')

    fireEvent.click(disabledItem)
    expect(items[2].onSelect).not.toHaveBeenCalled()
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('supports Home and End alongside arrow navigation', async () => {
    const user = userEvent.setup()
    render(<OverflowMenu label="Comic corrections" items={makeItems()} />)

    const trigger = screen.getByRole('button', { name: 'Comic corrections' })
    trigger.focus()
    await user.keyboard('{ArrowDown}')

    const items = within(screen.getByRole('menu')).getAllByRole('menuitem')
    await user.keyboard('{End}')
    expect(document.activeElement).toBe(items[2])
    await user.keyboard('{Home}')
    expect(document.activeElement).toBe(items[0])
  })

  it('wraps arrow navigation around the item list', async () => {
    const user = userEvent.setup()
    render(<OverflowMenu label="Comic corrections" items={makeItems()} />)

    const trigger = screen.getByRole('button', { name: 'Comic corrections' })
    trigger.focus()
    await user.keyboard('{ArrowDown}')

    const items = within(screen.getByRole('menu')).getAllByRole('menuitem')
    expect(document.activeElement).toBe(items[0])
    await user.keyboard('{ArrowUp}')
    expect(document.activeElement).toBe(items[2])
  })

  it('runs the item action and restores focus to the trigger', async () => {
    const items = makeItems()
    render(<OverflowMenu label="Comic corrections" items={items} />)

    const trigger = screen.getByRole('button', { name: 'Comic corrections' })
    const menu = await openMenu()
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'First' }))

    expect(items[0].onSelect).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes on Tab so keyboard focus can leave the region', () => {
    render(<OverflowMenu label="Comic corrections" items={makeItems()} />)

    const trigger = screen.getByRole('button', { name: 'Comic corrections' })
    fireEvent.click(trigger)
    const menu = screen.getByRole('menu')
    fireEvent.keyDown(within(menu).getAllByRole('menuitem')[0], { key: 'Tab' })

    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('clamps the surface inside the viewport and flips above when there is no room below', async () => {
    const items = makeItems()
    render(<OverflowMenu label="Comic corrections" items={items} />)

    const trigger = screen.getByRole('button', { name: 'Comic corrections' })
    // Near the bottom-right of a short viewport: the surface must not escape.
    stubTriggerRect(trigger, { left: 300, right: 344, top: 700, bottom: 744 })
    vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(760)
    Object.defineProperty(document.documentElement, 'clientWidth', {
      configurable: true,
      value: 320,
    })

    fireEvent.click(trigger)
    const menu = await screen.findByRole('menu')

    await vi.waitFor(() => {
      expect(menu.style.visibility).not.toBe('hidden')
    })

    // Estimated menu box is 3 items * 44px + 8px padding = 140px, and the
    // fallback width is 240px.
    // Below the trigger there is 760 - 748 = 12px, so the surface flips above.
    expect(menu.style.top).toBe('556px')
    // 320 - 240 - 8 = 72px is the rightmost left edge that keeps it on screen.
    expect(menu.style.left).toBe('72px')
  })

  it('opens below the trigger when there is room', async () => {
    render(<OverflowMenu label="Comic corrections" items={makeItems()} />)

    const trigger = screen.getByRole('button', { name: 'Comic corrections' })
    stubTriggerRect(trigger, { left: 16, right: 60, top: 100, bottom: 144 })
    vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(900)
    Object.defineProperty(document.documentElement, 'clientWidth', {
      configurable: true,
      value: 1280,
    })

    fireEvent.click(trigger)
    const menu = await screen.findByRole('menu')

    await vi.waitFor(() => {
      expect(menu.style.visibility).not.toBe('hidden')
    })
    expect(menu.style.top).toBe('148px')
    expect(menu.style.left).toBe('16px')
  })

  it('renders no trigger affordance when there is nothing to correct', async () => {
    render(<OverflowMenu label="Comic corrections" items={[]} />)

    const trigger = screen.getByRole('button', { name: 'Comic corrections' })
    fireEvent.click(trigger)
    expect(screen.queryByRole('menu')).toBeNull()
  })
})