import { vi } from 'vitest'
import { cast } from '../utils/cast'
import { isFunction } from '../utils/runtimeChecks'

type InjectableFunction = (...args: never[]) => void
type InjectableFunctionTable = Record<string, InjectableFunction>
type ImportOriginal = <OriginalModule = object>() => Promise<OriginalModule>
type ModuleDoubleFactory = (importOriginal: ImportOriginal) => object | Promise<object>

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
  factory: ModuleDoubleFactory,
): Promise<void> {
  // SAFETY: this is the same generic actual-module boundary exposed by Vitest.
  // The captured namespace contains the real exports before this factory's
  // doubles are installed, and each caller supplies its own module type.
  const importOriginal = cast<ImportOriginal>(async () => moduleExports)
  const doubles = await factory(importOriginal)
  for (const [exportName, replacement] of Object.entries(doubles)) {
    const descriptor = Object.getOwnPropertyDescriptor(moduleExports, exportName)
    if (descriptor?.value === replacement) continue

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

    // Mutate object-valued service namespaces in place instead of replacing the
    // whole export. Dependent modules capture the original object reference, so
    // replacing it breaks live bindings; mutating preserves the reference while
    // installing the supplied spies.
    if (
      descriptor?.value !== null &&
      typeof descriptor?.value === 'object' &&
      replacement !== null &&
      typeof replacement === 'object' &&
      !Array.isArray(descriptor.value) &&
      !Array.isArray(replacement)
    ) {
      for (const [key, value] of Object.entries(replacement)) {
        ;(descriptor.value as Record<string, unknown>)[key] = value
      }
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
