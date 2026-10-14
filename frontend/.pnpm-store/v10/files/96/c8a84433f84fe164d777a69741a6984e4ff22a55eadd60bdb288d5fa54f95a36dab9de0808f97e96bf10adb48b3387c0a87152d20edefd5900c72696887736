import { h as WebSocketNetworkFrameEventMap, i as HandlersMap, n as HandlersController, r as HandlersControllerState, t as AnyHandler } from "../_chunks/handlers-controller.js";
import { n as SharedOptions, t as LifeCycleEventEmitter } from "../_chunks/shared-options.js";
import { c as HttpNetworkFrameEventMap, i as NetworkReadyState, n as DefineNetworkOptions, t as InterceptorSource } from "../_chunks/interceptor-source.js";
import { PartialDeep } from "type-fest";
//#region src/node/glossary.d.ts
interface SetupServerCommon {
  /**
   * The current ready state of the underlying network.
   */
  readonly readyState: NetworkReadyState;
  /**
   * Starts the request interception based on the previously provided request handlers.
   *
   * @see {@link https://mswjs.io/docs/api/setup-server/listen `server.listen()` API reference}
   */
  listen: (options?: PartialDeep<SharedOptions>) => void;
  /**
   * Stops the request interception by restoring all augmented modules.
   *
   * @see {@link https://mswjs.io/docs/api/setup-server/close `server.close()` API reference}
   */
  close: () => void;
  /**
   * Prepends given request handlers to the list of existing handlers.
   *
   * @see {@link https://mswjs.io/docs/api/setup-server/use `server.use()` API reference}
   */
  use: (...handlers: Array<AnyHandler>) => void;
  /**
   * Marks all request handlers that respond using `res.once()` as unused.
   *
   * @see {@link https://mswjs.io/docs/api/setup-server/restore-handlers `server.restore-handlers()` API reference}
   */
  restoreHandlers: () => void;
  /**
   * Resets request handlers to the initial list given to the `setupServer` call, or to the explicit next request handlers list, if given.
   *
   * @see {@link https://mswjs.io/docs/api/setup-server/reset-handlers `server.reset-handlers()` API reference}
   */
  resetHandlers: (...nextHandlers: Array<AnyHandler>) => void;
  /**
   * Returns a readonly list of currently active request handlers.
   *
   * @see {@link https://mswjs.io/docs/api/setup-server/list-handlers `server.listHandlers()` API reference}
   */
  listHandlers: () => ReadonlyArray<AnyHandler>;
  /**
   * Life-cycle events.
   * Life-cycle events allow you to subscribe to the internal library events occurring during the request/response handling.
   *
   * @see {@link https://mswjs.io/docs/api/life-cycle-events Life-cycle Events API reference}
   */
  events: LifeCycleEventEmitter<HttpNetworkFrameEventMap & WebSocketNetworkFrameEventMap>;
}
interface SetupServer extends SetupServerCommon {
  /**
   * Wraps the given function in a boundary. Any changes to the
   * network behavior (e.g. adding runtime request handlers via
   * `server.use()`) will be scoped to this boundary only.
   * @param callback A function to run (e.g. a test)
   *
   * @see {@link https://mswjs.io/docs/api/setup-server/boundary `server.boundary()` API reference}
   */
  boundary: <Args extends Array<any>, R>(callback: (...args: Args) => R) => (...args: Args) => R;
}
//#endregion
//#region src/node/setup-server.d.ts
export declare const defaultNetworkOptions: DefineNetworkOptions<[InterceptorSource]>;
/**
 * Enables request interception in Node.js with the given request handlers.
 * @see {@link https://mswjs.io/docs/api/setup-server `setupServer()` API reference}
 */
export declare function setupServer(...handlers: Array<AnyHandler>): SetupServer;
//#endregion
//#region src/node/async-handlers-controller.d.ts
export declare class AsyncHandlersController extends HandlersController {
  #private;
  constructor(initialHandlers: Array<AnyHandler>);
  protected getState(): {
    initialHandlers: HandlersMap;
    handlers: HandlersMap;
  };
  protected setState(nextState: HandlersControllerState): void;
  boundary<Args extends Array<any>, R>(callback: (...args: Args) => R): (...args: Args) => R;
}
//#endregion
export type { SetupServer };
//# sourceMappingURL=index.d.ts.map