import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import OverlayPortal from '../components/OverlayPortal'

afterEach(() => {
  document.getElementById('comic-pile-overlay-root')?.remove()
  document.getElementById('comic-pile-overlay-root-dialog')?.remove()
  document.getElementById('comic-pile-overlay-root-global-effect')?.remove()
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
  expect(overlayRoot).toHaveAttribute('data-overlay-layer', 'menu')
  expect(overlayRoot).toHaveClass('comic-pile-overlay-root')
  expect(overlayRoot).toHaveClass('comic-pile-overlay-root--menu')
  expect(overlayRoot).toContainElement(menu)
  expect(overlayRoot?.parentElement).toBe(document.body)
})

it('applies the canonical shared layer contract to interactive overlays', async () => {
  render(
    <OverlayPortal>
      <button type="button">Overlay action</button>
    </OverlayPortal>,
  )

  const action = await screen.findByRole('button', { name: 'Overlay action' })
  const overlayRoot = document.getElementById('comic-pile-overlay-root')

  expect(overlayRoot).toHaveClass('comic-pile-overlay-root--menu')
  expect(overlayRoot).toHaveAttribute('data-overlay-layer', 'menu')
  expect(overlayRoot).toContainElement(action)
})

it('keeps dialogs in a higher independent stacking root than menus', async () => {
  render(
    <>
      <OverlayPortal>
        <div role="menu">Actions</div>
      </OverlayPortal>
      <OverlayPortal layer="dialog">
        <div role="dialog">Edit thread</div>
      </OverlayPortal>
    </>,
  )

  const menu = await screen.findByRole('menu')
  const dialog = await screen.findByRole('dialog')
  const menuRoot = document.getElementById('comic-pile-overlay-root')
  const dialogRoot = document.getElementById('comic-pile-overlay-root-dialog')

  expect(menuRoot).toHaveAttribute('data-overlay-layer', 'menu')
  expect(menuRoot).toHaveClass('comic-pile-overlay-root--menu')
  expect(menuRoot).toContainElement(menu)
  expect(dialogRoot).toHaveAttribute('data-overlay-layer', 'dialog')
  expect(dialogRoot).toHaveClass('comic-pile-overlay-root--dialog')
  expect(dialogRoot).toContainElement(dialog)
  expect(menuRoot).not.toBe(dialogRoot)
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

  await waitFor(() => {
    expect(document.getElementById('comic-pile-overlay-root')).toHaveTextContent(
      'First text overlaySecond text overlay',
    )
  })

  first.unmount()

  const overlayRoot = document.getElementById('comic-pile-overlay-root')
  expect(overlayRoot).toBeInTheDocument()
  expect(overlayRoot?.isConnected).toBe(true)
  expect(overlayRoot).toHaveTextContent('Second text overlay')

  second.unmount()
  expect(document.getElementById('comic-pile-overlay-root')).not.toBeInTheDocument()
})
