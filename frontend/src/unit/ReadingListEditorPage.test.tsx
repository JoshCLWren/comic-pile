import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ReadingListEditorPage from '../pages/ReadingListEditorPage'

vi.mock('../components/CustomCBLBuilder', () => ({
  default: ({ initialListId, planId }: { initialListId?: number; planId?: number }) => (
    <div data-testid="mock-cbl-builder" data-list-id={initialListId} data-plan-id={planId ?? ''} />
  ),
}))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reading-lists/:id" element={<ReadingListEditorPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ReadingListEditorPage', () => {
  it('opens the owned Reading List in the existing editor', () => {
    renderAt('/reading-lists/12')

    expect(screen.getByRole('heading', { name: 'Edit Reading List' })).toBeInTheDocument()
    expect(screen.getByTestId('mock-cbl-builder')).toHaveAttribute('data-list-id', '12')
    expect(screen.getByTestId('mock-cbl-builder')).toHaveAttribute('data-plan-id', '')
  })

  it('passes the originating plan so the list order can be applied to it', () => {
    renderAt('/reading-lists/12?planId=34')

    expect(screen.getByTestId('mock-cbl-builder')).toHaveAttribute('data-plan-id', '34')
  })

  it.each([
    ['a non-numeric plan id', '/reading-lists/12?planId=abc'],
    ['a zero plan id', '/reading-lists/12?planId=0'],
    ['an unsafe plan id', '/reading-lists/12?planId=9007199254740993'],
  ])('ignores %s and still opens the list editor', (_label, path) => {
    renderAt(path)

    expect(screen.getByTestId('mock-cbl-builder')).toHaveAttribute('data-list-id', '12')
    expect(screen.getByTestId('mock-cbl-builder')).toHaveAttribute('data-plan-id', '')
  })

  it.each([
    ['a non-numeric id', '/reading-lists/not-a-list'],
    ['zero', '/reading-lists/0'],
    ['a fractional id', '/reading-lists/1.5'],
    ['an unsafe integer', '/reading-lists/9007199254740993'],
  ])('rejects %s instead of opening the editor', (_label, path) => {
    renderAt(path)

    expect(screen.getByRole('alert')).toHaveTextContent('Reading List not found.')
    expect(screen.queryByTestId('mock-cbl-builder')).not.toBeInTheDocument()
  })
})
