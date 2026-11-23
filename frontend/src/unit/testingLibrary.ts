import { createElement, type ReactElement, type ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import {
  render as baseRender,
  renderHook as baseRenderHook,
  type RenderHookOptions,
  type RenderOptions,
} from '@testing-library/react'
import { queryClient } from '../query/queryClient'
import { cast } from '../utils/cast'

export * from '@testing-library/react'

type Wrapper = RenderOptions['wrapper']

function makeWrapper(innerWrapper: Wrapper) {
  return ({ children }: { children: ReactNode }): ReactElement =>
    createElement(
      QueryClientProvider,
      { client: queryClient },
      innerWrapper ? createElement(innerWrapper, null, children) : children,
    )
}

/** Render with the same process-wide QueryClient used by the application. */
export const render = cast<typeof baseRender>(
  (ui: ReactNode, options?: RenderOptions) =>
    baseRender(ui, { ...options, wrapper: makeWrapper(options?.wrapper) }),
)

/** Render a hook with the same process-wide QueryClient used by the application. */
export const renderHook = cast<typeof baseRenderHook>(
  <Result, Props>(callback: (initialProps: Props) => Result, options?: RenderHookOptions<Props>) =>
    baseRenderHook(callback, { ...options, wrapper: makeWrapper(options?.wrapper) }),
)
