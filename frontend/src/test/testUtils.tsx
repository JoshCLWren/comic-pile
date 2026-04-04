import { render } from '@testing-library/react'
import type { ReactNode } from 'react'

export function renderWithClient(ui: ReactNode) {
  return render(ui)
}
