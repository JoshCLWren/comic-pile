import {
  render as rtlRender,
  renderHook as rtlRenderHook,
  type RenderHookOptions,
  type RenderHookResult,
  type RenderOptions,
  type RenderResult,
} from '@testing-library/react'
import type { PropsWithChildren, ReactElement, ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

function createQueryWrapper(innerWrapper?: (children: ReactNode) => ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={client}>
        {innerWrapper ? innerWrapper(children) : children}
      </QueryClientProvider>
    )
  }
}

export function renderHookWithClient<Result, Props>(
  render: (props: Props) => Result,
  options?: RenderHookOptions<Props> & { innerWrapper?: (children: ReactNode) => ReactNode },
): RenderHookResult<Result, Props> {
  const { innerWrapper, ...restOptions } = options ?? {}
  return rtlRenderHook(render, { wrapper: createQueryWrapper(innerWrapper), ...restOptions })
}

export function renderWithClient(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'> & { innerWrapper?: (children: ReactNode) => ReactNode },
): RenderResult {
  const { innerWrapper, ...restOptions } = options ?? {}
  return rtlRender(ui, { wrapper: createQueryWrapper(innerWrapper), ...restOptions })
}
