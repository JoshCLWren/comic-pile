import { _ as Handler, a as RequestHandler, v as HandlerKind, y as MaybePromise } from "./request-handler.js";
import { n as Path, r as PathParams, t as Match } from "./match-request-url.js";
import { DefaultEventMap, Emitter, TypedEvent } from "rettime";
import { WebSocketClientHandle, WebSocketConnectionEventData, WebSocketConnectionInfo, WebSocketData, WebSocketExtension, WebSocketExtensionApi, WebSocketExtensionMessage, WebSocketServerHandle } from "@mswjs/interceptors/WebSocket";
//#region src/graphql/graphql-subscription-event.d.ts
interface GraphQLSubscriptionEventInit {
  operationName: string;
  query: string;
  variables: Record<string, unknown>;
  request: Request;
}
/**
 * Emitted when a GraphQL subscription is established over an
 * intercepted WebSocket connection (i.e. matched by a subscription
 * handler and resolved).
 *
 * @note The event is referenced by the WebSocket frame event map so
 * the life-cycle event emitters derived from it (e.g. `server.events`)
 * are typed correctly. It lives in its own module so the emitting
 * `msw/graphql` module doesn't pull the entire frame graph, and the
 * core stays free of the `graphql` dependency (the event carries
 * plain data only).
 */
declare class GraphQLSubscriptionEvent extends TypedEvent<void, void, 'graphql:subscription'> {
  readonly operationName: string;
  readonly query: string;
  readonly variables: Record<string, unknown>;
  readonly request: Request;
  constructor(init: GraphQLSubscriptionEventInit);
}
//#endregion
//#region src/core/experimental/on-unhandled-frame.d.ts
type UnhandledFrameHandle = UnhandledFrameStrategy | UnhandledFrameCallback;
type UnhandledFrameStrategy = 'bypass' | 'warn' | 'error';
type UnhandledFrameCallback = (args: {
  frame: AnyNetworkFrame;
  defaults: UnhandledFrameDefaults;
}) => Promise<void> | void;
type UnhandledFrameDefaults = {
  warn: () => void;
  error: () => void;
};
//#endregion
//#region src/core/experimental/frames/network-frame.d.ts
type AnyNetworkFrame = NetworkFrame<string, unknown, any>;
type ExtractFrameEvents<Frame> = Frame extends NetworkFrame<any, any, infer Events> ? Events : never;
interface NetworkFrameResolutionContext {
  baseUrl?: string | URL;
  quiet?: boolean;
}
/**
 * The base for the network frames. Extend this abstract class
 * to implement custom network frames.
 */
declare abstract class NetworkFrame<Protocol extends string, Data, Events extends DefaultEventMap> {
  readonly protocol: Protocol;
  readonly data: Data;
  events: Emitter<Events>;
  constructor(protocol: Protocol, data: Data);
  abstract getHandlers(controller: HandlersController): Array<AnyHandler>;
  /**
   * Resolve the current frame against the given list of handlers.
   * Optionally, use a custom resolution context to control behaviors
   * like `baseUrl`.
   *
   * Returns `true` if the frame was handled, `false` if it wasn't, and `null`
   * if its handling was skipped (e.g. the frame was bypassed).
   */
  abstract resolve(handlers: Array<AnyHandler>, onUnhandledFrame: UnhandledFrameHandle, resolutionContext?: NetworkFrameResolutionContext): Promise<boolean | null>;
  /**
   * Perform this network frame as-is.
   */
  abstract passthrough(): void;
  /**
   * Error the underling network frame.
   * @param reason The reason for the error.
   */
  abstract errorWith(reason?: unknown): void;
  /**
   * Get a message to be used when this frame is unhandled.
   */
  abstract getUnhandledMessage(): Promise<string>;
}
//#endregion
//#region src/core/experimental/frames/websocket-frame.d.ts
interface WebSocketNetworkFrameOptions {
  connection: WebSocketConnectionEventData;
}
type WebSocketNetworkFrameEventMap = {
  /**
   * Emitted when a WebSocket connection is intercepted,
   * before any handlers are resolved against it.
   */
  'websocket:connection': WebSocketConnectionEvent$1;
  /**
   * Emitted when the WebSocket connection errors.
   * This includes initial connection errors as well as runtime errors
   * after the connection has been established.
   */
  'websocket:error': WebSocketErrorEvent;
  'graphql:subscription': GraphQLSubscriptionEvent;
  unhandledException: WebSocketErrorEvent;
};
declare class WebSocketConnectionEvent$1<DataType extends {
  url: URL;
  protocols: string | Array<string> | undefined;
} = {
  url: URL;
  protocols: string | Array<string> | undefined;
}, ReturnType = void, EventType extends string = string> extends TypedEvent<DataType, ReturnType, EventType> {
  readonly url: URL;
  readonly protocols: string | Array<string> | undefined;
  constructor(type: EventType, data: DataType);
}
declare class WebSocketErrorEvent<DataType extends {
  url: URL;
  protocols: string | Array<string> | undefined;
  error: unknown;
} = {
  url: URL;
  protocols: string | Array<string> | undefined;
  error: unknown;
}, ReturnType = void, EventType extends string = string> extends WebSocketConnectionEvent$1<DataType, ReturnType, EventType> {
  readonly error: unknown;
  constructor(type: EventType, data: DataType);
}
declare abstract class WebSocketNetworkFrame extends NetworkFrame<'ws', {
  connection: WebSocketConnectionEventData;
}, WebSocketNetworkFrameEventMap> {
  constructor(options: WebSocketNetworkFrameOptions);
  getHandlers(controller: HandlersController): Array<AnyHandler>;
  resolve(handlers: Array<WebSocketHandler<AnyWebSocketExtension>>, onUnhandledFrame: UnhandledFrameHandle, resolutionContext?: NetworkFrameResolutionContext): Promise<boolean | null>;
  getUnhandledMessage(): Promise<string>;
}
//#endregion
//#region src/ws/websocket-handler.d.ts
type WebSocketHandlerParsedResult = {
  match: Match;
};
interface WebSocketHandlerOptions {
  /**
   * WebSocket extensions applied to every connection matched by this handler,
   * left to right. The last one applied encodes and decodes the traffic,
   * and every one of them extends the connection event with its own API.
   */
  extensions?: ReadonlyArray<AnyWebSocketExtension>;
}
type AnyWebSocketExtension = WebSocketExtension<unknown, unknown>;
/**
 * The connection event of a handler with the given extension:
 * the connection speaks the extension's messages and the event
 * carries the extension's own API (e.g. rooms).
 */
type WebSocketHandlerConnectionEvent<Extension extends AnyWebSocketExtension = WebSocketExtension> = WebSocketConnectionEvent<WebSocketExtensionMessage<Extension>> & WebSocketExtensionApi<Extension>;
type WebSocketHandlerEventMap<Extension extends AnyWebSocketExtension = WebSocketExtension> = {
  connection: WebSocketHandlerConnectionEvent<Extension>;
};
/**
 * The connection matched by a handler.
 *
 * @note Typed against the connection handles, not the connection classes,
 * so a handler accepts connections living anywhere (e.g. in another
 * runtime, or a custom implementation of the handles).
 */
interface WebSocketHandlerConnection<Message = WebSocketData> {
  client: WebSocketClientHandle<Message>;
  server: WebSocketServerHandle<Message>;
  info: WebSocketConnectionInfo;
  params: PathParams;
}
declare class WebSocketConnectionEvent<Message = WebSocketData> extends TypedEvent<void, void, 'connection'> implements WebSocketHandlerConnection<Message> {
  readonly client: WebSocketClientHandle<Message>;
  readonly server: WebSocketServerHandle<Message>;
  readonly info: WebSocketConnectionInfo;
  readonly params: PathParams;
  constructor(connection: WebSocketHandlerConnection<Message>);
}
/**
 * The connection resolved by a handler: the matched connection
 * extended with the handler extension's own API.
 */
type WebSocketHandlerResolvedConnection<Extension extends AnyWebSocketExtension = WebSocketExtension> = WebSocketHandlerConnection<WebSocketExtensionMessage<Extension>> & WebSocketExtensionApi<Extension>;
interface WebSocketResolutionContext {
  baseUrl?: string;
  /**
   * An emit-only reference to the network frame's events.
   * Allows handlers to emit additional events not covered by the frame
   * into the network's life-cycle event stream (e.g. `server.events`).
   */
  events?: Pick<Emitter<WebSocketNetworkFrameEventMap>, 'emit'>;
  [kAutoConnect]?: boolean;
}
declare const kEmitter: unique symbol;
declare const kConnect: unique symbol;
declare const kAutoConnect: unique symbol;
declare class WebSocketHandler<Extension extends AnyWebSocketExtension = WebSocketExtension> extends Handler {
  #private;
  protected readonly url: Path;
  id: string;
  callFrame?: string;
  readonly kind = "websocket";
  protected [kEmitter]: Emitter<WebSocketHandlerEventMap<Extension>>;
  protected readonly extensions: ReadonlyArray<AnyWebSocketExtension>;
  constructor(url: Path, options?: WebSocketHandlerOptions);
  parse(args: {
    url: string | URL;
    resolutionContext?: WebSocketResolutionContext;
  }): WebSocketHandlerParsedResult;
  predicate(args: {
    url: string | URL;
    parsedResult: WebSocketHandlerParsedResult;
  }): boolean;
  test(url: string | URL, resolutionContext?: WebSocketResolutionContext & {
    strict?: boolean;
  }): boolean;
  run(connection: WebSocketConnectionEventData, resolutionContext?: WebSocketResolutionContext): Promise<WebSocketHandlerResolvedConnection<Extension> | null>;
  protected [kConnect](connection: WebSocketHandlerResolvedConnection<Extension>): boolean;
  log(connection: WebSocketConnectionEventData): () => void;
}
//#endregion
//#region src/core/experimental/handlers-controller.d.ts
type AnyHandler = RequestHandler | WebSocketHandler<AnyWebSocketExtension>;
type HandlerOfKind<Kind extends HandlerKind> = Extract<AnyHandler, {
  kind: Kind;
}>;
type HandlersMapOfKind<Kind extends HandlerKind> = { [K in Kind]?: Array<HandlerOfKind<K>>; };
type HandlersMap = HandlersMapOfKind<HandlerKind>;
interface HandlersControllerState {
  initialHandlers: HandlersMap;
  handlers: HandlersMap;
}
declare abstract class HandlersController {
  #private;
  protected getInitialState(initialHandlers: Array<AnyHandler>): HandlersControllerState;
  protected abstract getState(): HandlersControllerState;
  protected abstract setState(nextState: Partial<HandlersControllerState>): void;
  currentHandlers(): Array<AnyHandler>;
  /**
   * Return the list of explicitly registered handlers.
   * Unlike `currentHandlers()`, this excludes sibling handlers,
   * which are an implementation detail (e.g. the WebSocket upgrade
   * handler or the GraphQL subscription transport).
   */
  listHandlers(): Array<AnyHandler>;
  /**
   * Return the list of handlers of the given kind.
   */
  getHandlersByKind<Kind extends HandlerKind>(kind: Kind): Array<HandlerOfKind<Kind>>;
  use(nextHandlers: Array<AnyHandler>): void;
  reset(nextHandlers: Array<AnyHandler>): void;
  restore(): void;
  dispose(): MaybePromise<void>;
}
declare class InMemoryHandlersController extends HandlersController {
  #private;
  constructor(initialHandlers: Array<AnyHandler>);
  protected getState(): HandlersControllerState;
  protected setState(nextState: Partial<HandlersControllerState>): void;
}
//#endregion
export { ExtractFrameEvents as _, InMemoryHandlersController as a, UnhandledFrameHandle as b, WebSocketHandler as c, WebSocketHandlerOptions as d, WebSocketResolutionContext as f, AnyNetworkFrame as g, WebSocketNetworkFrameEventMap as h, HandlersMap as i, WebSocketHandlerConnection as l, WebSocketNetworkFrame as m, HandlersController as n, AnyWebSocketExtension as o, kConnect as p, HandlersControllerState as r, WebSocketConnectionEvent as s, AnyHandler as t, WebSocketHandlerEventMap as u, NetworkFrame as v, UnhandledFrameStrategy as x, NetworkFrameResolutionContext as y };
//# sourceMappingURL=handlers-controller.d.ts.map