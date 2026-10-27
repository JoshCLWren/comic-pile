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

function Harness({ initialValue = '', onSubmit }: { initialValue?: string; onSubmit?: (value: string) => void }) {
  const [value, setValue] = useState(initialValue)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit?.(value)
      }}
    >
      <ManualPickerSearch activeOptions={activeOptions} value={value} onChange={setValue} />
      <button type="submit">Pick this series</button>
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

  it('consumes Enter while a failed search has no matches instead of submitting an old choice', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<Harness initialValue="1" onSubmit={onSubmit} />)

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.type(input, 'zzz')
    expect(screen.getByRole('option', { name: 'No matching series' })).toBeInTheDocument()

    // The picker owns Enter while its list is open, even with zero matches.
    expect(fireEvent.keyDown(input, { key: 'Enter' })).toBe(false)
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByTestId('picked-value')).toHaveTextContent('1')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
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

  it('dismisses only its own list on Escape inside the real Modal dialog', async () => {
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

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Pick manually' })).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
