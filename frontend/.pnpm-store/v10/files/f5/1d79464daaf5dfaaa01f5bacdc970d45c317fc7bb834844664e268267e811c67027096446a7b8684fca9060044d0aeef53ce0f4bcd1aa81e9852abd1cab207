import { b as UnhandledFrameHandle } from "./handlers-controller.js";
import { DefaultEventMap, Emitter } from "rettime";
//#region src/core/shared-options.d.ts
interface SharedOptions {
  /**
   * Specifies how to react to a network frame (e.g. a request or
   * a WebSocket connection) that has no corresponding handler.
   * Warns on unhandled frames by default.
   *
   * @example worker.start({ onUnhandledFrame: 'bypass' })
   * @example worker.start({ onUnhandledFrame: 'warn' })
   * @example server.listen({ onUnhandledFrame: 'error' })
   * @example server.listen({ onUnhandledFrame({ frame, defaults }) { defaults.warn() } })
   */
  onUnhandledFrame?: UnhandledFrameHandle;
}
type LifeCycleEventEmitter<EventMap extends DefaultEventMap> = Pick<Emitter<EventMap>, 'on' | 'removeListener' | 'removeAllListeners'>;
//#endregion
export { SharedOptions as n, LifeCycleEventEmitter as t };
//# sourceMappingURL=shared-options.d.ts.map