import { a as RequestHandler, b as UnionToIntersection } from "./request-handler.js";
import { _ as ExtractFrameEvents, b as UnhandledFrameHandle, g as AnyNetworkFrame, n as HandlersController, t as AnyHandler, v as NetworkFrame, y as NetworkFrameResolutionContext } from "./handlers-controller.js";
import { HttpRequestEventMap, Interceptor } from "@mswjs/interceptors";
import { DefaultEventMap, Emitter, TypedEvent, TypedListenerOptions } from "rettime";
import { WebSocketEventMap } from "@mswjs/interceptors/WebSocket";
//#region src/core/experimental/frames/http-frame.d.ts
interface HttpNetworkFrameOptions {
  id?: string;
  request: Request;
}
declare class RequestEvent<DataType extends {
  requestId: string;
  request: Request;
} = {
  requestId: string;
  request: Request;
}, ReturnType = void, EventType extends string = string> extends TypedEvent<DataType, ReturnType, EventType> {
  readonly requestId: string;
  readonly request: Request;
  constructor(type: EventType, data: DataType);
}
declare class ResponseEvent<DataType extends {
  requestId: string;
  request: Request;
  response: Response;
} = {
  requestId: string;
  request: Request;
  response: Response;
}, ReturnType = void, EventType extends string = string> extends TypedEvent<DataType, ReturnType, EventType> {
  readonly requestId: string;
  readonly request: Request;
  readonly response: Response;
  constructor(type: EventType, data: DataType);
}
declare class UnhandledExceptionEvent<DataType extends {
  error: Error;
  requestId: string;
  request: Request;
} = {
  error: Error;
  requestId: string;
  request: Request;
}, ReturnType = void, EventType extends string = string> extends TypedEvent<DataType, ReturnType, EventType> {
  readonly error: Error;
  readonly requestId: string;
  readonly request: Request;
  constructor(type: EventType, data: DataType);
}
type HttpNetworkFrameEventMap = {
  'request:start': RequestEvent;
  'request:match': RequestEvent;
  'request:unhandled': RequestEvent;
  'request:end': RequestEvent;
  'response:mocked': ResponseEvent;
  'response:bypass': ResponseEvent;
  unhandledException: UnhandledExceptionEvent;
};
declare abstract class HttpNetworkFrame extends NetworkFrame<'http', {
  id: string;
  request: Request;
}, HttpNetworkFrameEventMap> {
  constructor(options: HttpNetworkFrameOptions);
  getHandlers(controller: HandlersController): Array<AnyHandler>;
  abstract respondWith(response?: Response): void;
  getUnhandledMessage(): Promise<string>;
  resolve(handlers: Array<RequestHandler>, onUnhandledFrame: UnhandledFrameHandle, resolutionContext?: NetworkFrameResolutionContext): Promise<boolean | null>;
}
//#endregion
//#region src/core/experimental/sources/network-source.d.ts
declare class NetworkFrameEvent<DataType = void, ReturnType = void, EventType extends string = string> extends TypedEvent<DataType, ReturnType, EventType> {
  frame: AnyNetworkFrame;
  constructor(type: string, frame: AnyNetworkFrame);
}
type NetworkSourceEventMap<Frame extends AnyNetworkFrame> = {
  frame: NetworkFrameEvent<Frame>;
};
type ExtractSourceEvents<Source> = Source extends NetworkSource<infer Frame> ? ExtractFrameEvents<Frame> : never;
declare abstract class NetworkSource<Frame extends AnyNetworkFrame = AnyNetworkFrame> {
  protected emitter: Emitter<NetworkSourceEventMap<Frame>>;
  constructor();
  abstract enable(): unknown | Promise<unknown>;
  queue(frame: Frame): Promise<void>;
  on<Type extends keyof NetworkSourceEventMap<Frame>>(type: Type, listener: Emitter.Listener<typeof this.emitter, Type>, options?: TypedListenerOptions): void;
  disable(): void | Promise<void>;
}
//#endregion
//#region src/core/experimental/define-network.d.ts
type MergeEventMaps<Sources extends Array<NetworkSource<any>>> = UnionToIntersection<ExtractSourceEvents<Sources[number]>> extends (infer R) ? R extends Record<string, any> ? R : DefaultEventMap : DefaultEventMap;
type MaybePromise<T> = Extract<T, Promise<unknown>> extends never ? void : Promise<void>;
interface DefineNetworkOptions<Sources extends Array<NetworkSource<any>>> {
  /**
   * List of the network sources.
   * Every network source emits frames, and every frame describes how
   * to handle the various network scenarios, like mocking a response,
   * erroring the request, or performing it as-is.
   */
  sources: Sources;
  /**
   * List of handlers to describe the network.
   */
  handlers?: Array<AnyHandler> | HandlersController;
  context?: NetworkFrameResolutionContext;
  onUnhandledFrame?: UnhandledFrameHandle;
}
interface NetworkApi<Sources extends Array<NetworkSource<any>>> extends NetworkHandlersApi {
  readyState: NetworkReadyState;
  /**
   * Enable the network interception and handling.
   */
  enable: () => MaybePromise<ReturnType<Sources[number]['enable']>>;
  /**
   * Disable the network interception and handling.
   */
  disable: () => MaybePromise<ReturnType<Sources[number]['disable']>>;
  /**
   * Configure the network instance with additional options.
   * The options provided in the `.configure()` call will override the same
   * options in the `defineNetwork()` call.
   */
  configure: (options: Partial<DefineNetworkOptions<Sources>>) => void;
  events: Emitter<MergeEventMaps<Sources>>;
}
interface NetworkHandlersApi {
  use: (...handlers: Array<AnyHandler>) => void;
  resetHandlers: (...handlers: Array<AnyHandler>) => void;
  restoreHandlers: () => void;
  listHandlers: () => ReadonlyArray<AnyHandler>;
}
declare enum NetworkReadyState {
  DISABLED = 0,
  ENABLED = 1
}
/**
 * Define a network instance with the given configuration.
 * @example
 * import { InterceptorSource } from 'msw/experimental'
 * import { handlers } from './handlers'
 *
 * const network = defineNetwork({
 *   sources: [new InterceptorSource({ interceptors })],
 *   handlers,
 * })
 * await network.enable()
 */
declare function defineNetwork<Sources extends Array<NetworkSource<any>>>(options: DefineNetworkOptions<Sources>): NetworkApi<Sources>;
//#endregion
//#region src/core/experimental/sources/interceptor-source.d.ts
interface InterceptorSourceOptions {
  interceptors: Array<Interceptor<HttpRequestEventMap | WebSocketEventMap>>;
}
/**
 * Create a network source from the given list of interceptors.
 */
declare class InterceptorSource extends NetworkSource {
  #private;
  constructor(options: InterceptorSourceOptions);
  enable(): void;
  disable(): void;
}
//#endregion
export { defineNetwork as a, HttpNetworkFrameEventMap as c, NetworkReadyState as i, DefineNetworkOptions as n, NetworkSource as o, NetworkApi as r, HttpNetworkFrame as s, InterceptorSource as t };
//# sourceMappingURL=interceptor-source.d.ts.map