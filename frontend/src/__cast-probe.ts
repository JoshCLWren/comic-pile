import { vi } from 'vitest'

const fileListAsPartial = {
  length: 0,
  item: () => null,
} as Partial<FileList>

const fileListResult: FileList = fileListAsPartial as FileList

const dtItemsAsPartial = {
  length: 0,
  add: () => null,
  remove: () => {},
  clear: () => {},
  item: () => null,
} as Partial<DataTransferItemList>

const dtItemsResult: DataTransferItemList = dtItemsAsPartial as DataTransferItemList

const ctxAsPartial = {
  fillStyle: '',
  strokeStyle: '',
  lineWidth: 0,
  font: '',
  textAlign: 'left',
  textBaseline: 'top',
  fillRect: vi.fn(),
  strokeRect: vi.fn(),
  fillText: vi.fn(),
} as Partial<CanvasRenderingContext2D>

const ctxResult: CanvasRenderingContext2D = ctxAsPartial as CanvasRenderingContext2D

const navTimings = [
  {
    domContentLoadedEventEnd: 12,
    loadEventEnd: 34,
  },
] as Partial<PerformanceNavigationTiming>[]

const entryResult: PerformanceEntry[] = navTimings as PerformanceEntry[]

const mediaSimple = { matches: true } as MediaQueryList
const matchMediaFn = (() => ({ matches: true })) as (q: string) => MediaQueryList

declare const scrolling: (x?: number, y?: number) => void
const scrollNoop = (_x?: number | ScrollToOptions, _y?: number) => undefined

export {
  fileListResult,
  dtItemsResult,
  ctxResult,
  entryResult,
  mediaSimple,
  matchMediaFn,
  scrolling,
  scrollNoop,
}