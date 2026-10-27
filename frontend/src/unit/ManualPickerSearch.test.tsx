import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import Modal from '../components/Modal'
import {
  ManualPickerSearch,
  type ManualPickerSearchOption,
} from '../pages/RollPage/components/ManualPickerSearch'

const activeOptions: ManualPickerSearchOption[] = [
  { id: 1, label: 'Saga (Comic)' },
  { id: 2, label: 'Superman (Comic) · Up next: #5' },
  { id: 3, label: 'Superman (Comic) · Up next: #9' },
]

function Harness({
  initialValue = '',
  onSubmit,
  pending = false,
  disabled = false,
}: {
  initialValue?: string
  onSubmit?: (value: string) => void
  pending?: boolean
  disabled?: boolean
}) {
  const [value, setValue] = useState(initialValue)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit?.(value)
      }}
    >
      <ManualPickerSearch
        activeOptions={activeOptions}
        value={value}
        onChange={setValue}
        pending={pending}
        disabled={disabled}
      />
      <button type="submit" disabled={!value}>
        Pick this series
      </button>
      <output data-testid="picked-value">{value}</output>
    </form>
  )
}

describe('ManualPickerSearch', () => {
  it('filters on the visible series identity and reports a no-match state', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const input = screen.getByRole('combobox')
    await user.type(input, 'super')

    expect(screen.getByRole('option', { name: 'Superman (Comic) · Up next: #5' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Superman (Comic) · Up next: #9' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Saga (Comic)' })).not.toBeInTheDocument()

    // The already-known disambiguating identity is searchable too.
    await user.clear(input)
    await user.type(input, '#9')
    expect(screen.getByRole('option', { name: 'Superman (Comic) · Up next: #9' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Superman (Comic) · Up next: #5' })).not.toBeInTheDocument()

    await user.clear(input)
    await user.type(input, 'nothing matches')
    expect(screen.getByRole('option', { name: 'No matching series' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )
    expect(screen.queryByRole('option', { name: 'Saga (Comic)' })).not.toBeInTheDocument()
  })

  it('filters on thread identity ID even when labels have no disambiguation', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const input = screen.getByRole('combobox')

    // A thread id is usable identity when the label carries no disambiguating text.
    await user.type(input, '2')
    expect(screen.getByRole('option', { name: 'Superman (Comic) · Up next: #5' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Saga (Comic)' })).not.toBeInTheDocument()

    await user.clear(input)
    await user.type(input, '3')
    expect(screen.getByRole('option', { name: 'Superman (Comic) · Up next: #9' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Saga (Comic)' })).not.toBeInTheDocument()

    await user.clear(input)
    await user.type(input, '1')
    expect(screen.getByRole('option', { name: 'Saga (Comic)' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Superman (Comic) · Up next: #5' })).not.toBeInTheDocument()
  })

  it('exposes exactly one selected option, matching aria-activedescendant', async () => {
    const user = userEvent.setup()
    render(<Harness initialValue="1" />)

    const input = screen.getByRole('combobox')
    await user.click(input)
    // Move virtual focus off the saved choice so a stale value-based
    // aria-selected would advertise a second selection.
    await user.keyboard('{ArrowDown}')

    const selected = screen
      .getAllByRole('option')
      .filter((option) => option.getAttribute('aria-selected') === 'true')

    expect(selected).toHaveLength(1)
    expect(input).toHaveAttribute('aria-activedescendant', selected[0].id)
    expect(screen.getByRole('option', { name: 'Superman (Comic) · Up next: #5' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('option', { name: 'Saga (Comic)' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
  })

  it('resolves keyboard selection to the exact Thread when names collide', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.keyboard('{ArrowDown}{Enter}')

    expect(screen.getByTestId('picked-value')).toHaveTextContent('2')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByTestId('manual-picker-selection')).toHaveTextContent(
      'Selected: Superman (Comic) · Up next: #5',
    )
  })

  it('clears the previous commit when the reader types a new search', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<Harness initialValue="1" onSubmit={onSubmit} />)

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.type(input, 'zzz')
    expect(screen.getByRole('option', { name: 'No matching series' })).toBeInTheDocument()

    // Typing a new search invalidates the earlier choice, so neither the
    // "Pick this series" button nor Enter can submit the hidden old series.
    expect(screen.getByTestId('picked-value')).toHaveTextContent('')
    expect(screen.getByRole('button', { name: 'Pick this series' })).toBeDisabled()
    expect(screen.queryByTestId('manual-picker-selection')).not.toBeInTheDocument()

    expect(fireEvent.keyDown(input, { key: 'Enter' })).toBe(false)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('clears the query with the clear control and restores the full list', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const input = screen.getByRole('combobox')
    await user.type(input, 'saga')
    expect(screen.getByRole('option', { name: 'Saga (Comic)' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Clear search' }))
    expect(input).toHaveValue('')
    expect(screen.getByRole('option', { name: 'Saga (Comic)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Superman (Comic) · Up next: #5' })).toBeInTheDocument()
  })

  it('keeps the highlighted option in view as arrow keys move past the visible rows', async () => {
    const user = userEvent.setup()
    const scrollIntoView = vi.fn()
    const original = Element.prototype.scrollIntoView
    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      writable: true,
      value: scrollIntoView,
    })

    try {
      render(<Harness />)
      await user.click(screen.getByRole('combobox'))
      // Clear any scrollIntoView triggered by opening, so we only measure navigation.
      scrollIntoView.mockClear()
      await user.keyboard('{ArrowDown}{ArrowDown}')

      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
    } finally {
      Object.defineProperty(Element.prototype, 'scrollIntoView', {
        configurable: true,
        writable: true,
        value: original,
      })
    }
  })

  it('lets the first Escape reach the dialog while the option list is open', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()

    render(
      <Modal isOpen title="Pick manually" onClose={onClose}>
        <ManualPickerSearch
          activeOptions={activeOptions}
          value=""
          onChange={() => {}}
        />
      </Modal>,
    )

    // The real Modal autofocuses the search input, which opens the list.
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{Escape}')

    // docs/FRONTEND_VISUAL_GRAMMAR.md: the topmost Modal owns Escape. The
    // picker may collapse its popup, but it must not swallow the press and
    // force a second or third Escape before the dialog closes.
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('lets one Escape close the dialog even while a search query is active', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()

    render(
      <Modal isOpen title="Pick manually" onClose={onClose}>
        <ManualPickerSearch
          activeOptions={activeOptions}
          value=""
          onChange={() => {}}
        />
      </Modal>,
    )

    const input = screen.getByRole('combobox')
    await user.type(input, 'super')
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('navigates with both arrow keys and tolerates navigation on an empty result', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.keyboard('{ArrowDown}')
    const secondId = screen.getByRole('option', { name: 'Superman (Comic) · Up next: #5' }).id
    expect(input).toHaveAttribute('aria-activedescendant', secondId)

    await user.keyboard('{ArrowUp}')
    const firstId = screen.getByRole('option', { name: 'Saga (Comic)' }).id
    expect(input).toHaveAttribute('aria-activedescendant', firstId)

    // Zero matches must not leave a dangling active option or throw.
    await user.type(input, 'zzz')
    await user.keyboard('{ArrowDown}{ArrowUp}')
    expect(input).not.toHaveAttribute('aria-activedescendant')
  })

  it('submits the form when Enter is pressed after a keyboard commit closed the list', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<Harness initialValue="3" onSubmit={onSubmit} />)

    const input = screen.getByRole('combobox')
    await user.click(input)
    // A keyboard commit collapses the popup and keeps focus in the combobox.
    await user.keyboard('{Enter}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('1')
  })

  it('ignores keyboard interaction while the picker is pending', async () => {
    const onSubmit = vi.fn()
    render(<Harness pending onSubmit={onSubmit} />)

    const input = screen.getByRole('combobox')
    expect(input).toBeDisabled()

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
