import { render, screen } from './testingLibrary'
import { expect, it, vi } from 'vitest'
import LazyDice3D from '../components/LazyDice3D'
import { injectModuleDoubles } from './injectModuleDoubles'

await injectModuleDoubles(await import('../components/Dice3D'), () => ({
  default: () => <div data-testid="dice-3d" />,
}))

it('renders lazy dice component', async () => {
  render(<LazyDice3D sides={6} value={1} />)
  expect(await screen.findByTestId('dice-3d')).toBeInTheDocument()
})
