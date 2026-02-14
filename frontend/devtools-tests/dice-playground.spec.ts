import { expect, test } from '@playwright/test'

const DICE_SIDES = [4, 6, 8, 10, 12, 20]

test.describe('Dice Playground Visual Baselines', () => {
  test('renders each die with inspectable faces', async ({ page }) => {
    await page.goto('/dice-playground.html')

    const canvasHost = page.getByTestId('dice-playground-canvas')
    await expect(canvasHost).toBeVisible()

    for (const sides of DICE_SIDES) {
      await page.getByTestId(`die-button-${sides}`).click()
      await expect(page.getByTestId('dice-label')).toHaveText(`d${sides}`)

      const sampleFaces = [1, Math.ceil(sides / 2), sides]
      for (const face of sampleFaces) {
        await page.getByTestId(`value-button-${face}`).click()
        await expect(page.getByTestId('value-label')).toHaveText(String(face))
        await expect(canvasHost).toHaveScreenshot(`dice-playground-d${sides}-v${face}.png`, {
          maxDiffPixelRatio: 0.015,
        })
      }
    }
  })
})
