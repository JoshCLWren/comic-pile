import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import PositionMenu from '../components/PositionMenu'
import { PositionMenuProvider } from '../contexts/PositionMenuContext'

const mockThread = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  status: 'active' as const,
  queue_position: 1,
  issues_remaining: 5,
  notes: null,
  total_issues: null,
  next_unread_issue_id: null,
  next_unread_issue_number: null,
  reading_progress: null,
  blocking_reasons: [],
  is_blocked: false,
  created_at: '2024-01-01T00:00:00Z',
}

function renderMenu() {
  return render(
    <PositionMenuProvider>
      <PositionMenu
        thread={mockThread}
        onMoveToFront={vi.fn()}
        onReposition={vi.fn()}
        onMoveToBack={vi.fn()}
        onEdit={vi.fn()}
        onDependencies={vi.fn()}
        onDelete={vi.fn()}
      />
    </PositionMenuProvider>,
  )
}

afterEach(() => {
  cleanup()
})

it('mounts the position menu inside the shared overlay root', async () => {
  const user = userEvent.setup()
  renderMenu()

  await user.click(screen.getByRole('button', { name: 'Thread actions' }))

  const menu = await screen.findByRole('menu', { name: 'Thread actions' })
  const overlayRoot = document.querySelector('[data-overlay-root="true"]')

  expect(overlayRoot).not.toBeNull()
  expect(overlayRoot).toContainElement(menu)
  expect(menu.parentElement).toBe(overlayRoot)
})

it('releases the shared overlay root after the menu unmounts', async () => {
  const user = userEvent.setup()
  const view = renderMenu()

  await user.click(screen.getByRole('button', { name: 'Thread actions' }))
  await screen.findByRole('menu', { name: 'Thread actions' })

  view.unmount()

  await waitFor(() => {
    expect(document.querySelector('[data-overlay-root="true"]')).toBeNull()
  })
})
