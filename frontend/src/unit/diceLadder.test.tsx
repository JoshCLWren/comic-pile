import { expect, it } from 'vitest'
import { DICE_LADDER } from '../components/diceLadder'

it('defines the expected dice ladder', () => {
  expect(DICE_LADDER).toEqual([4, 6, 8, 10, 12, 20])
})
