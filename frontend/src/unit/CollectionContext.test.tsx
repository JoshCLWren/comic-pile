import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  CollectionProvider,
  useCollections,
} from '../contexts/CollectionContext'

describe('removed Collections compatibility shim', () => {
  it('renders children without creating a provider-owned lifecycle', () => {
    render(
      <CollectionProvider>
        <span>provider-free child</span>
      </CollectionProvider>,
    )

    expect(screen.getByText('provider-free child')).toBeInTheDocument()
  })

  it('returns one stable inert state with no persistence or mutation behavior', async () => {
    const firstState = useCollections()
    const secondState = useCollections()

    expect(secondState).toBe(firstState)
    expect(firstState.collections).toEqual([])
    expect(firstState.activeCollectionId).toBeNull()
    expect(firstState.isLoading).toBe(false)
    expect(firstState.error).toBeNull()

    expect(firstState.setActiveCollectionId(42)).toBeUndefined()
    expect(firstState.retry()).toBeUndefined()
    await expect(firstState.createCollection({ name: 'Removed' })).resolves.toBeUndefined()
    await expect(
      firstState.updateCollection(1, { name: 'Still removed' }),
    ).resolves.toBeUndefined()
    await expect(firstState.deleteCollection(1)).resolves.toBeUndefined()
    await expect(firstState.moveCollection(1, 2)).resolves.toBeUndefined()

    expect(useCollections()).toBe(firstState)
    expect(firstState.collections).toEqual([])
    expect(firstState.activeCollectionId).toBeNull()
  })
})
