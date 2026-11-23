import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from './testingLibrary'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingListEditorPage from '../pages/ReadingListEditorPage'
import { customCBLApi, type CustomCBL } from '../services/api-custom-cbl'
import { existingList as existingListFixture } from './fixtures/customCblFixture'

const originalCustomCBLApi = { ...customCBLApi }
const getList = vi.fn<typeof customCBLApi.get>()
const listLists = vi.fn<typeof customCBLApi.list>()
const existingList: CustomCBL = { ...existingListFixture, mode: 'loose' }
const ownedList: CustomCBL = { ...existingList, id: 12, entries: [], issue_count: 0 }

beforeEach(() => {
  Object.assign(customCBLApi, { get: getList, list: listLists })
  vi.clearAllMocks()
  getList.mockResolvedValue(ownedList)
  listLists.mockResolvedValue([ownedList])
})

afterEach(() => {
  Object.assign(customCBLApi, originalCustomCBLApi)
})

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/reading-lists/:id" element={<ReadingListEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReadingListEditorPage', () => {
  it('opens the owned Reading List in the existing editor', async () => {
    renderAt('/reading-lists/12')

    expect(screen.getByRole('heading', { name: 'Edit Reading List' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Name')).toHaveValue(existingList.name)
    expect(getList).toHaveBeenCalledWith(12)
  })

  it.each([
    ['a non-numeric id', '/reading-lists/not-a-list'],
    ['zero', '/reading-lists/0'],
    ['a fractional id', '/reading-lists/1.5'],
    ['an unsafe integer', '/reading-lists/9007199254740993'],
  ])('rejects %s instead of opening the editor', (_label, path) => {
    renderAt(path)

    expect(screen.getByRole('alert')).toHaveTextContent('Reading List not found.')
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()
    expect(getList).not.toHaveBeenCalled()
  })
})
