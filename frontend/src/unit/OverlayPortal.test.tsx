import { render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import OverlayPortal from '../components/OverlayPortal'

afterEach(() => {
  document.getElementById('comic-pile-overlay-root')?.remove()
})

it('renders overlay content outside the application root', async () => {
  render(
    <OverlayPortal>
      <div role="menu">Actions</div>
    </OverlayPortal>,
  )

  const menu = await screen.findByRole('menu')
  const overlayRoot = document.getElementById('comic-pile-overlay-root')

  expect(overlayRoot).toHaveAttribute('data-overlay-root', 'true')
  expect(overlayRoot).toContainElement(menu)
  expect(overlayRoot?.parentElement).toBe(document.body)
})

it('shares one overlay root across concurrent overlays', async () => {
  const first = render(
    <OverlayPortal>
      <div>First overlay</div>
    </OverlayPortal>,
  )
  const second = render(
    <OverlayPortal>
      <div>Second overlay</div>
    </OverlayPortal>,
  )

  await screen.findByText('Second overlay')

  expect(document.querySelectorAll('#comic-pile-overlay-root')).toHaveLength(1)
  expect(document.getElementById('comic-pile-overlay-root')).toHaveTextContent(
    'First overlaySecond overlay',
  )

  first.unmount()
  expect(document.getElementById('comic-pile-overlay-root')).toHaveTextContent('Second overlay')

  second.unmount()
  expect(document.getElementById('comic-pile-overlay-root')).not.toBeInTheDocument()
})

it('keeps the shared root connected while a direct text portal remains mounted', async () => {
  const first = render(<OverlayPortal>First text overlay</OverlayPortal>)
  const second = render(<OverlayPortal>Second text overlay</OverlayPortal>)

  await screen.findByText('Second text overlay')

  first.unmount()

  const overlayRoot = document.getElementById('comic-pile-overlay-root')
  expect(overlayRoot).toBeInTheDocument()
  expect(overlayRoot?.isConnected).toBe(true)
  expect(overlayRoot).toHaveTextContent('Second text overlay')

  second.unmount()
  expect(document.getElementById('comic-pile-overlay-root')).not.toBeInTheDocument()
})
