import { h as WebSocketNetworkFrameEventMap, t as AnyHandler } from "../_chunks/handlers-controller.js";
import { n as SharedOptions, t as LifeCycleEventEmitter } from "../_chunks/shared-options.js";
import { c as HttpNetworkFrameEventMap, i as NetworkReadyState, n as DefineNetworkOptions, o as NetworkSource, s as HttpNetworkFrame, t as InterceptorSource } from "../_chunks/interceptor-source.js";
import { Emitter, TypedEvent } from "rettime";
//#region src/browser/glossary.d.ts
interface StringifiedResponse extends ResponseInit {
  body: string | ArrayBuffer | ReadableStream<Uint8Array> | null;
}
type FindWorker = (scriptUrl: string, mockServiceWorkerUrl: string) => boolean;
interface StartOptions extends SharedOptions {
  /**
   * Service Worker registration options.
   */
  serviceWorker?: {
    /**
     * Custom url to the worker script.
     * @default "/mockServiceWorker.js"
     */
    url?: string;
    options?: RegistrationOptions;
  };
  /**
   * Disables the logging of the intercepted requests
   * into browser's console.
   * @default false
   */
  quiet?: boolean;
  /**
   * A custom lookup function to find a Mock Service Worker in the list
   * of all registered Service Workers on the page.
   */
  findWorker?: FindWorker;
}
interface SetupWorker {
  /**
   * The current ready state of the underlying network.
   */
  readonly readyState: NetworkReadyState;
  /**
   * Registers and activates the mock Service Worker.
   *
   * @see {@link https://mswjs.io/docs/api/setup-worker/start `worker.start()` API reference}
   */
  start: (options?: StartOptions) => Promise<ServiceWorkerRegistration | undefined>;
  /**
   * Stops requests interception for the current client.
   *
   * @see {@link https://mswjs.io/docs/api/setup-worker/stop `worker.stop()` API reference}
   */
  stop: () => Promise<void> | void;
  /**
   * Prepends given request handlers to the list of existing handlers.
   * @param {Array<AnyHandler>} handlers List of runtime request handlers.
   *
   * @see {@link https://mswjs.io/docs/api/setup-worker/use `worker.use()` API reference}
   */
  use: (...handlers: Array<AnyHandler>) => void;
  /**
   * Marks all request handlers that respond using `res.once()` as unused.
   *
   * @see {@link https://mswjs.io/docs/api/setup-worker/restore-handlers `worker.restoreHandlers()` API reference}
   */
  restoreHandlers: () => void;
  /**
   * Resets request handlers to the initial list given to the `setupWorker` call, or to the explicit next request handlers list, if given.
   * @param {Array<AnyHandler>} nextHandlers List of the new initial request handlers.
   *
   * @see {@link https://mswjs.io/docs/api/setup-worker/reset-handlers `worker.resetHandlers()` API reference}
   */
  resetHandlers: (...nextHandlers: Array<AnyHandler>) => void;
  /**
   * Returns a readonly list of currently active request handlers.
   *
   * @see {@link https://mswjs.io/docs/api/setup-worker/list-handlers `worker.listHandlers()` API reference}
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
//#endregion
//#region src/browser/setup-worker.d.ts
/**
 * Sets up a requests interception in the browser with the given request handlers.
 * @param {Array<AnyHandler>} handlers List of request handlers.
 *
 * @see {@link https://mswjs.io/docs/api/setup-worker `setupWorker()` API reference}
 */
export declare function setupWorker(...handlers: Array<AnyHandler>): SetupWorker;
//#endregion
//#region src/browser/utils/worker-channel.d.ts
type WorkerChannelEventMap = {
  REQUEST: WorkerEvent<IncomingWorkerRequest>;
  RESPONSE: WorkerEvent<IncomingWorkerResponse>;
  REQUEST_ERROR: WorkerEvent<IncomingWorkerRequestError>;
  MOCKING_ENABLED: WorkerEvent<{
    client: {
      id: string;
      frameType: string;
    };
  }>;
  CLIENT_CLOSED: TypedEvent<never>;
  INTEGRITY_CHECK_RESPONSE: WorkerEvent<{
    packageVersion: string;
    checksum: string;
  }>;
  KEEPALIVE_RESPONSE: TypedEvent<never>;
};
/**
 * Request representation received from the worker message event.
 */
interface IncomingWorkerRequest extends Omit<Request, 'text' | 'body' | 'json' | 'blob' | 'arrayBuffer' | 'formData' | 'clone' | 'signal' | 'isHistoryNavigation' | 'isReloadNavigation'> {
  /**
   * Unique ID of the request generated once the request is
   * intercepted by the "fetch" event in the Service Worker.
   */
  id: string;
  body?: ArrayBuffer | null;
}
type IncomingWorkerResponse = {
  isMockedResponse: boolean;
  request: IncomingWorkerRequest;
  response: Pick<Response, 'type' | 'ok' | 'status' | 'statusText' | 'body' | 'headers' | 'redirected'>;
};
/**
 * Notification that a request has settled without producing a response
 * (e.g. a passthrough request failed with a network error).
 */
type IncomingWorkerRequestError = {
  request: Pick<IncomingWorkerRequest, 'id'>;
  error: Pick<Error, 'name' | 'message'>;
};
/**
 * Request modifications to apply to the passthrough request in the worker.
 */
interface PassthroughPayload {
  request: {
    /**
     * Request headers as a list of entries to support
     * multiple headers with the same name.
     */
    headers: Array<[string, string]>;
  };
}
type WorkerEventResponse = {
  MOCK_RESPONSE: [data: StringifiedResponse, transfer?: [ReadableStream<Uint8Array>]];
  PASSTHROUGH: [data: PassthroughPayload];
};
declare class WorkerEvent<DataType, ReturnType = any, EventType extends string = string> extends TypedEvent<DataType, ReturnType, EventType> {
  #private;
  constructor(workerEvent: MessageEvent);
  get ports(): readonly MessagePort[];
  /**
   * Reply directly to this event using its `MessagePort`.
   */
  postMessage<Type extends keyof WorkerEventResponse>(type: Type, ...rest: WorkerEventResponse[Type]): void;
}
/**
 * Map of the events that can be sent to the Service Worker
 * from any execution context.
 */
type OutgoingWorkerEvents = 'MOCK_ACTIVATE' | 'INTEGRITY_CHECK_REQUEST' | 'KEEPALIVE_REQUEST' | 'CLIENT_CLOSE';
interface WorkerChannelOptions {
  getWorker: () => Promise<ServiceWorker>;
}
declare class WorkerChannel extends Emitter<WorkerChannelEventMap> {
  #private;
  constructor(options: WorkerChannelOptions);
  /**
   * Send data to the Service Worker controlling this client.
   * This triggers the `message` event listener on ServiceWorkerGlobalScope.
   */
  postMessage(type: OutgoingWorkerEvents): void;
  /**
   * Terminal teardown. Removes the `navigator.serviceWorker` message listener
   * and all emitter subscriptions. The channel is not usable afterwards.
   */
  terminate(): void;
}
//#endregion
//#region src/browser/sources/service-worker-source.d.ts
interface ServiceWorkerSourceOptions {
  quiet?: boolean;
  serviceWorker: {
    url: string;
    options?: RegistrationOptions;
  };
  findWorker?: FindWorker;
}
type WorkerChannelRequestEvent = Emitter.Event<WorkerChannel, 'REQUEST', WorkerChannelEventMap>;
declare class ServiceWorkerSource extends NetworkSource<ServiceWorkerHttpNetworkFrame> {
  #private;
  /**
   * Create a new Service Worker source or reuse an existing one.
   * These sources act as a singleton and only get recreated if the options change.
   */
  static from(options: ServiceWorkerSourceOptions): Promise<ServiceWorkerSource>;
  workerPromise: Promise<[ServiceWorker, ServiceWorkerRegistration]>;
  constructor(options: ServiceWorkerSourceOptions);
  enable(): Promise<ServiceWorkerRegistration>;
  disable(): Promise<void>;
  /**
   * Terminal teardown. Unregisters the Service Worker, tears down the channel,
   * and clears timers. Called when the singleton is being replaced with one
   * that has different options. The instance is not usable afterwards.
   */
  terminate(): Promise<void>;
}
declare class ServiceWorkerHttpNetworkFrame extends HttpNetworkFrame {
  #private;
  constructor(options: {
    event: WorkerChannelRequestEvent;
    request: Request;
  });
  passthrough(): void;
  respondWith(response?: Response): void;
  errorWith(reason?: unknown): void;
}
//#endregion
//#region src/browser/sources/fallback-http-source.d.ts
interface FallbackHttpSourceOptions {
  quiet?: boolean;
}
declare class FallbackHttpSource extends InterceptorSource {
  #private;
  private readonly options;
  constructor(options: FallbackHttpSourceOptions);
  enable(): void;
  disable(): void;
}
//#endregion
//#region src/browser/default-network-options.d.ts
export declare function createDefaultNetworkOptions(workerUrl?: string): DefineNetworkOptions<[ServiceWorkerSource | FallbackHttpSource, InterceptorSource]>;
export declare const defaultNetworkOptions: DefineNetworkOptions<[FallbackHttpSource | ServiceWorkerSource, InterceptorSource]>;
//#endregion
export type { SetupWorker, StartOptions };
//# sourceMappingURL=index.d.ts.map