import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AppErrorBoundary from '../components/AppErrorBoundary'

function BrokenChild(): never {
  throw new Error('render exploded')
}

describe('AppErrorBoundary', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders children while the application is healthy', () => {
    render(
      <AppErrorBoundary>
        <div>Healthy application</div>
      </AppErrorBoundary>,
    )

    expect(screen.getByText('Healthy application')).toBeInTheDocument()
  })

  it('replaces a render crash with a visible reload path', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const reload = vi.spyOn(window.location, 'reload').mockImplementation(() => undefined)

    render(
      <AppErrorBoundary>
        <BrokenChild />
      </AppErrorBoundary>,
    )

    expect(screen.getByRole('heading', { name: 'ComicPile needs to reconnect' })).toBeInTheDocument()
    expect(consoleError).toHaveBeenCalledWith(
      'ComicPile application render failed',
      expect.any(Error),
      expect.any(Object),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Reload ComicPile' }))
    expect(reload).toHaveBeenCalledOnce()
  })
})
