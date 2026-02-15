import { render, RenderResult } from '@testing-library/react'
import { ReactElement } from 'react'

export function renderWithClient(ui: ReactElement): RenderResult {
  return render(ui)
}
