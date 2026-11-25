import { vi } from 'vitest'
import { cast } from '../utils/cast'
import { isFunction, isPlainObject } from '../utils/runtimeChecks'

type InjectableFunction = (...args: never[]) => void
type InjectableFunctionTable = Record<string, InjectableFunction>
type ImportOriginal = <OriginalModule = object>() => Promise<OriginalModule>
type ModuleDoubleMap<ModuleExports extends object> = Partial<
  Record<Extract<keyof ModuleExports, string>, unknown>
>
type ModuleDoubleFactory<ModuleExports extends object> = (
  importOriginal: ImportOriginal,
) => ModuleDoubleMap<ModuleExports> | Promise<ModuleDoubleMap<ModuleExports>>

/**
 * Installs explicit test doubles on Vitest's configurable ES-module exports.
 *
 * Unlike hoisted module replacement, this preserves every unmentioned export and
 * uses spies for function exports, so tests can inspect and reset the injected
 * boundary with the normal Vitest mock API. Object-valued service namespaces are
 * replaced directly because they are dependency containers rather than calls.
 */
export async function injectModuleDoubles<ModuleExports extends object>(
  moduleExports: ModuleExports,
  factory: ModuleDoubleFactory<ModuleExports>,
): Promise<void> {
  // SAFETY: this is the same generic actual-module boundary exposed by Vitest.
  // Snapshot the exports before installing doubles so wrappers retain the real
  // implementation instead of recursively reading their own replacement.
  const originalExports = { ...moduleExports }
  const importOriginal = cast<ImportOriginal>(async () => originalExports)
  const doubles = await factory(importOriginal)
  for (const [exportName, replacement] of Object.entries(doubles)) {
    const descriptor = Object.getOwnPropertyDescriptor(moduleExports, exportName)
    if (!descriptor || !descriptor.configurable) {
      throw new Error(`Cannot inject missing or non-configurable module export "${exportName}"`)
    }
    if (descriptor.value === replacement) continue

    if (isPlainObject(descriptor.value) && isPlainObject(replacement)) {
      for (const memberName of Object.keys(replacement)) {
        if (!(memberName in descriptor.value)) {
          throw new Error(`Cannot invent "${exportName}.${memberName}" on a module export`)
        }
      }
    }

    if (isFunction(descriptor?.value) && isFunction(replacement)) {
      // SAFETY: both property values were just checked as functions. Vitest's
      // transformed ES-module namespace is configurable and spyable; the record
      // view only exposes the string-keyed function table needed by vi.spyOn.
      const functionExports = cast<InjectableFunctionTable>(moduleExports)
      // SAFETY: the runtime function check above establishes the callable
      // contract; the injected implementation keeps the original export's args
      // and return behavior at each call site.
      const implementation = cast<InjectableFunction>(replacement)
      vi.spyOn(functionExports, exportName).mockImplementation(implementation)
      continue
    }

    Object.defineProperty(moduleExports, exportName, {
      configurable: true,
      enumerable: true,
      writable: true,
      value: replacement,
    })
  }
}
