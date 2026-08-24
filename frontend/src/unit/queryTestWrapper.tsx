import {
  render as rtlRender,
  renderHook as rtlRenderHook,
  type RenderHookOptions,
  type RenderHookResult,
  type RenderOptions,
  type RenderResult,
} from '@testing-library/react'
import type { PropsWithChildren, ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

function createQueryWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

export function renderHookWithClient<Result, Props>(
  render: (props: Props) => Result,
  options?: RenderHookOptions<Props>,
): RenderHookResult<Result, Props> {
  return rtlRenderHook(render, { wrapper: createQueryWrapper(), ...options })
}

export function renderWithClient(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>,
): RenderResult {
  return rtlRender(ui, { wrapper: createQueryWrapper(), ...options })
}
