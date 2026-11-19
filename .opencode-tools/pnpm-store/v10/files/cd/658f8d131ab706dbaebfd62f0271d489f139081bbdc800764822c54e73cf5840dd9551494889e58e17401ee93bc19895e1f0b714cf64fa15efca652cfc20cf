/**
 * A Vite plugin for Mock Service Worker.
 *
 * @example
 * // vite.config.ts
 * import { msw } from 'msw/vite'
 *
 * export default defineConfig({
 *   plugins: [msw()]
 * })
 *
 * @example
 * // src/{client,server}.ts
 * if (import.meta.env.DEV) {
 *   const { network } = await import('virtual:msw')
 *   const { handlers } = await import('./mocks/handlers')
 *
 *   network.configure({ handlers })
 *   await network.enable()
 * }
 *
 * @remarks
 * The worker script is served during development and emitted next to any
 * client bundle that imports `virtual:msw`. Guard mocking setup with
 * `import.meta.env.DEV` to exclude both from production builds.
 *
 * For application TypeScript projects that do not include the Vite config,
 * add `/// <reference types="msw/vite/client" />` to an included declaration file.
 */
/// <reference types="msw/vite/client" preserve="true" />
import { Plugin } from "vite";
//#region src/vite/plugin.d.ts
interface MswPluginOptions {
  /**
   * Use automatic integration or only provide the worker script for manual setup.
   * In worker-only mode, virtual modules are disabled.
   * @default "auto"
   */
  mode?: 'auto' | 'worker-only';
}
export declare function msw(options?: MswPluginOptions): Plugin;
//#endregion
export type { MswPluginOptions };
//# sourceMappingURL=index.d.ts.map