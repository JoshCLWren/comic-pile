import { t as Interceptor } from "../../interceptor-dtJZ_9QT.js";
import { TypedEvent } from "rettime";
//#region src/events/websocket.d.ts
/**
 * The connection information.
 */
interface WebSocketConnectionInfo {
  /**
   * The protocols supported by the WebSocket client.
   */
  protocols: string | Array<string> | undefined;
}
/**
 * An intercepted WebSocket connection: the client and the server handles.
 *
 * @note Typed against the handles, not the connection classes,
 * so that a connection living anywhere (in this process, in another
 * runtime, or in a custom implementation) can be given to whoever
 * consumes intercepted connections (e.g. a handler).
 */
interface WebSocketConnectionEventData<Message = WebSocketData> {
  /**
   * The incoming WebSocket client connection.
   */
  client: WebSocketClientHandle<Message>;
  /**
   * The original WebSocket server connection.
   */
  server: WebSocketServerHandle<Message>;
  info: WebSocketConnectionInfo;
}
/**
 * The connection intercepted by the `WebSocketInterceptor`:
 * both the client and the server live in this process.
 */
interface WebSocketInterceptedConnection<Message = WebSocketData> extends WebSocketConnectionEventData<Message> {
  client: WebSocketClientConnection<Message>;
  server: WebSocketServerConnection<Message>;
}
export declare class WebSocketConnectionEvent<Message = WebSocketData> extends TypedEvent<WebSocketInterceptedConnection<Message>, void, 'connection'> implements WebSocketInterceptedConnection<Message> {
  client: WebSocketClientConnection<Message>;
  server: WebSocketServerConnection<Message>;
  info: WebSocketConnectionInfo;
  constructor(data: WebSocketInterceptedConnection<Message>);
}
type WebSocketEventMap$1<Message = WebSocketData, Extension = {}> = {
  connection: WebSocketConnectionEvent<Message> & Extension;
};
//#endregion
//#region src/interceptors/WebSocket/utils/events.d.ts
declare const kCancelable: unique symbol;
declare const kDefaultPrevented: unique symbol;
/**
 * A `MessageEvent` superset that supports event cancellation
 * in Node.js. It's rather non-intrusive so it can be safely
 * used in the browser as well.
 *
 * @see https://github.com/nodejs/node/issues/51767
 */
export declare class CancelableMessageEvent<T = any> extends MessageEvent<T> {
  [kCancelable]: boolean;
  [kDefaultPrevented]: boolean;
  constructor(type: string, init: MessageEventInit<T>);
  get cancelable(): boolean;
  set cancelable(nextCancelable: boolean);
  get defaultPrevented(): boolean;
  set defaultPrevented(nextDefaultPrevented: boolean);
  preventDefault(): void;
}
interface CloseEventInit extends EventInit {
  code?: number;
  reason?: string;
  wasClean?: boolean;
}
export declare class CloseEvent extends Event {
  code: number;
  reason: string;
  wasClean: boolean;
  constructor(type: string, init?: CloseEventInit);
}
export declare class CancelableCloseEvent extends CloseEvent {
  [kCancelable]: boolean;
  [kDefaultPrevented]: boolean;
  constructor(type: string, init?: CloseEventInit);
  get cancelable(): boolean;
  set cancelable(nextCancelable: boolean);
  get defaultPrevented(): boolean;
  set defaultPrevented(nextDefaultPrevented: boolean);
  preventDefault(): void;
}
//#endregion
//#region src/interceptors/WebSocket/web-socket-transport.d.ts
type WebSocketData = string | ArrayBuffer | Blob | ArrayBufferView<ArrayBuffer>;
type WebSocketTransportEventMap = {
  incoming: MessageEvent<WebSocketData>;
  outgoing: MessageEvent<WebSocketData>;
  close: CloseEvent;
};
type StrictEventListenerOrEventListenerObject<EventType extends Event> = ((this: WebSocket, event: EventType) => void) | {
  handleEvent(this: WebSocket, event: EventType): void;
};
interface WebSocketTransport {
  addEventListener<EventType extends keyof WebSocketTransportEventMap>(event: EventType, listener: StrictEventListenerOrEventListenerObject<WebSocketTransportEventMap[EventType]> | null, options?: boolean | AddEventListenerOptions): void;
  dispatchEvent<EventType extends keyof WebSocketTransportEventMap>(event: WebSocketTransportEventMap[EventType]): boolean;
  /**
   * Send the data from the server to this client.
   */
  send(data: WebSocketData): void;
  /**
   * Close the client connection.
   */
  close(code?: number, reason?: string): void;
}
//#endregion
//#region src/interceptors/WebSocket/web-socket-override.d.ts
type WebSocketEventListener<EventType extends Event = Event> = (this: WebSocket, event: EventType) => void;
declare const kPassthroughPromise: unique symbol;
declare const kOnSend: unique symbol;
declare const kClose: unique symbol;
declare class WebSocketOverride extends EventTarget implements WebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;
  url: string;
  protocol: string;
  extensions: string;
  binaryType: BinaryType;
  readyState: WebSocket['readyState'];
  bufferedAmount: number;
  private _onopen;
  private _onmessage;
  private _onerror;
  private _onclose;
  private [kPassthroughPromise];
  private [kOnSend]?;
  constructor(url: string | URL, protocols?: string | Array<string>);
  set onopen(listener: WebSocketEventListener | null);
  get onopen(): WebSocketEventListener | null;
  set onmessage(listener: WebSocketEventListener<MessageEvent<WebSocketData>> | null);
  get onmessage(): WebSocketEventListener<MessageEvent<WebSocketData>> | null;
  set onerror(listener: WebSocketEventListener | null);
  get onerror(): WebSocketEventListener | null;
  set onclose(listener: WebSocketEventListener<CloseEvent> | null);
  get onclose(): WebSocketEventListener<CloseEvent> | null;
  /**
   * @see https://websockets.spec.whatwg.org/#ref-for-dom-websocket-send%E2%91%A0
   */
  send(data: WebSocketData): void;
  close(code?: number, reason?: string): void;
  private [kClose];
  addEventListener<K extends keyof WebSocketEventMap>(type: K, listener: (this: WebSocket, event: WebSocketEventMap[K]) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: string, listener: EventListenerOrEventListenerObject, options?: boolean | AddEventListenerOptions): void;
  removeEventListener<K extends keyof WebSocketEventMap>(type: K, callback: EventListenerOrEventListenerObject | null, options?: boolean | EventListenerOptions): void;
}
//#endregion
//#region src/interceptors/WebSocket/web-socket-class-transport.d.ts
/**
 * Abstraction over the given mock `WebSocket` instance that allows
 * for controlling that instance (e.g. sending and receiving messages).
 */
declare class WebSocketClassTransport extends EventTarget implements WebSocketTransport {
  protected readonly socket: WebSocketOverride;
  constructor(socket: WebSocketOverride);
  addEventListener<EventType extends keyof WebSocketTransportEventMap>(type: EventType, callback: StrictEventListenerOrEventListenerObject<WebSocketTransportEventMap[EventType]> | null, options?: boolean | AddEventListenerOptions): void;
  dispatchEvent<EventType extends keyof WebSocketTransportEventMap>(event: WebSocketTransportEventMap[EventType]): boolean;
  send(data: WebSocketData): void;
  close(code: number, reason?: string): void;
}
//#endregion
//#region src/interceptors/WebSocket/web-socket-server-connection.d.ts
declare const kEmitter$1: unique symbol;
declare const kSend: unique symbol;
interface WebSocketServerEventMap<Message = WebSocketData> {
  open: Event;
  message: MessageEvent<Message>;
  error: Event;
  close: CloseEvent;
}
/**
 * The handle to the original WebSocket server connection: its controls.
 * A `WebSocketServerConnection` is a handle bound to a connection
 * in this process.
 */
export declare abstract class WebSocketServerHandle<Message = WebSocketData> {
  extension?: WebSocketExtension<unknown, unknown>;
  abstract connect(): void;
  abstract send(data: Message): void;
  abstract close(): void;
  abstract addEventListener<EventType extends keyof WebSocketServerEventMap<Message>>(event: EventType, listener: WebSocketEventListener<WebSocketServerEventMap<Message>[EventType]>, options?: AddEventListenerOptions | boolean): void;
  abstract removeEventListener<EventType extends keyof WebSocketServerEventMap<Message>>(event: EventType, listener: WebSocketEventListener<WebSocketServerEventMap<Message>[EventType]>, options?: EventListenerOptions | boolean): void;
}
/**
 * The WebSocket server instance represents the actual production
 * WebSocket server connection. It's idle by default but you can
 * establish it by calling `server.connect()`.
 */
export declare class WebSocketServerConnection<Message = WebSocketData> implements WebSocketServerHandle<Message> {
  #private;
  private readonly client;
  private readonly transport;
  private readonly createConnection;
  /**
   * A WebSocket instance connected to the original server.
   */
  private realWebSocket?;
  private mockCloseController;
  private realCloseController;
  private [kEmitter$1];
  /**
   * An optional extension applied to the data crossing this connection:
   * `send()` encodes, incoming server frames are decoded
   * before being dispatched as `message` events.
   */
  extension?: WebSocketExtension<unknown, unknown>;
  /**
   * The intercepted connection this server belongs to.
   * Provided by the interceptor once both connections exist.
   */
  [kExtensionContext]?: WebSocketExtensionContext<unknown>;
  constructor(client: WebSocketOverride, transport: WebSocketClassTransport, createConnection: () => WebSocket);
  /**
   * The `WebSocket` instance connected to the original server.
   * Accessing this before calling `server.connect()` will throw.
   */
  get socket(): WebSocket;
  /**
   * The ready state of the connection to the original WebSocket server.
   * Equals `WebSocket.CLOSED` until `server.connect()` is called.
   */
  get readyState(): number;
  /**
   * Open connection to the original WebSocket server.
   */
  connect(): void;
  /**
   * Listen for the incoming events from the original WebSocket server.
   */
  addEventListener<EventType extends keyof WebSocketServerEventMap<Message>>(event: EventType, listener: WebSocketEventListener<WebSocketServerEventMap<Message>[EventType]>, options?: AddEventListenerOptions | boolean): void;
  /**
   * Remove the listener for the given event.
   */
  removeEventListener<EventType extends keyof WebSocketServerEventMap<Message>>(event: EventType, listener: WebSocketEventListener<WebSocketServerEventMap<Message>[EventType]>, options?: EventListenerOptions | boolean): void;
  /**
   * Send data to the original WebSocket server.
   * @example
   * server.send('hello')
   * server.send(new Blob(['hello']))
   * server.send(new TextEncoder().encode('hello'))
   */
  send(data: Message): void;
  /**
   * Return the original WebSocket, throwing if
   * the connection to the original server was not established.
   */
  private assertConnected;
  private [kSend];
  /**
   * Close the actual server connection.
   */
  close(): void;
  private handleIncomingMessage;
  private handleMockClose;
  private handleRealClose;
}
//#endregion
//#region src/interceptors/WebSocket/web-socket-extension.d.ts
declare const kExtensionContext: unique symbol;
/**
 * The messages the given extension encodes and decodes.
 *
 * @note Inferred from the `encode()` parameter alone. Inferring from the
 * whole class would also consider the return type of `decode()`, where a
 * `Generator<Message>` (whose return type defaults to `any`) would widen
 * the messages to `any`.
 */
type WebSocketExtensionMessage<Extension> = Extension extends {
  encode(message: infer Message, context: never): unknown;
} ? Message : never;
/**
 * The API the given extension adds to the connection event.
 */
type WebSocketExtensionApi<Extension> = Extension extends WebSocketExtension<unknown, infer Api> ? Api : never;
/**
 * The result of an extension method: a single value, an iterator
 * over multiple values, or `undefined` for no values at all.
 *
 * @note Only iterators (objects with a `next()` method, like generators)
 * are unfolded. Iterables that are not iterators, like strings, arrays,
 * or typed arrays, are treated as a single value so array-shaped
 * messages remain unambiguous.
 */
type WebSocketExtensionResult<Value> = Value | Iterator<Value, Value | void> | undefined;
/**
 * The intercepted connection an extension operates on.
 */
interface WebSocketExtensionContext<Message = WebSocketData> {
  client: WebSocketClientHandle<Message>;
  server: WebSocketServerHandle<Message>;
  info: WebSocketConnectionInfo;
}
interface WebSocketExtensionMessageContext<Message = WebSocketData> extends WebSocketExtensionContext<Message> {
  /**
   * The connection whose data is being encoded or decoded:
   * the `client` for data crossing the client connection,
   * the `server` for data crossing the original server connection.
   */
  connection: WebSocketClientHandle<Message> | WebSocketServerHandle<Message>;
}
/**
 * A WebSocket extension: the server-side implementation of a protocol layered on top of
 * WebSocket (e.g. Socket.IO): its message framing (`encode`/`decode`),
 * its session as spoken by a server endpoint (`connect`/`receive`),
 * and the server API it adds to every connection (`extend`).
 *
 * The interceptor decides *when* each part applies: `send()` encodes,
 * frames are decoded before being dispatched as `message` events,
 * `connect` and `receive` frames are sent while the mocked connection
 * plays the server, and the extension is exposed on the connection event.
 *
 * An extension is invisible to the connection consumer: `client.send()`,
 * `server.send()`, and the `message` events all operate on messages,
 * and the session frames never surface. Raw frames forwarded between
 * the client and the original server (passthrough) are never touched.
 *
 * A method returns a single value for a one-to-one mapping,
 * an iterator (e.g. a generator) to unfold one input into many,
 * or nothing to drop the input.
 *
 * @example
 * class SocketIo extends WebSocketExtension<SocketIoMessage, { rooms: Rooms }> {
 *   match({ client }) {
 *     return client.url.searchParams.has('EIO')
 *   }
 *   encode(message) { ... }
 *   decode(data) { ... }
 *   connect() { ... }
 *   receive(data) { ... }
 *   extend({ client }) {
 *     return { rooms: new Rooms(client) }
 *   }
 * }
 *
 * new WebSocketInterceptor({ extensions: [new SocketIo()] })
 */
export declare abstract class WebSocketExtension<Message = WebSocketData, Extension = {}> {
  /**
   * Whether this extension applies to the given connection.
   * Allows applying the extension to a subset of intercepted connections.
   */
  match?(context: WebSocketExtensionContext<Message>): boolean;
  /**
   * Encode the given message into the raw frame(s) to send to the peer.
   */
  abstract encode(message: Message, context: WebSocketExtensionMessageContext<Message>): WebSocketExtensionResult<WebSocketData>;
  /**
   * Decode the given raw frame into the message(s) to dispatch
   * as `message` events. Return nothing to swallow the frame
   * (e.g. protocol control frames).
   */
  abstract decode(data: WebSocketData, context: WebSocketExtensionMessageContext<Message>): WebSocketExtensionResult<Message>;
  /**
   * The raw frame(s) a server of this extension's protocol sends once the
   * connection is established (e.g. a session handshake).
   * Sent to the client by the interceptor when the mocked connection
   * opens, unless a connection to the original server was established,
   * in which case the original server speaks for itself.
   */
  connect?(context: WebSocketExtensionContext<Message>): WebSocketExtensionResult<WebSocketData>;
  /**
   * The raw frame(s) a server of this extension's protocol sends back in response
   * to the given client frame (e.g. a control frame acknowledgement),
   * the way a WebSocket endpoint answers a ping with a pong.
   * Applied by the interceptor under the same condition as `connect`.
   */
  receive?(data: WebSocketData, context: WebSocketExtensionContext<Message>): WebSocketExtensionResult<WebSocketData>;
  /**
   * The server API this extension adds to the given connection
   * (e.g. rooms). Exposed on the connection event alongside
   * the `client` and the `server`.
   */
  extend?(context: WebSocketExtensionContext<Message>): Extension;
  /**
   * Apply this extension to the given connection.
   * From then on, both the client and the server of that connection
   * encode the data they send and decode the data they receive.
   *
   * @note Accepts a connection carrying any messages: applying an
   * extension is what makes a connection carry this extension's
   * messages, so it must not demand them upfront (e.g. a raw
   * connection from the `connection` event).
   */
  apply(connection: {
    client: WebSocketClientHandle<unknown>;
    server: WebSocketServerHandle<unknown>;
  }): void;
}
//#endregion
//#region src/interceptors/WebSocket/web-socket-client-connection.d.ts
declare const kEmitter: unique symbol;
interface WebSocketClientEventMap<Message = WebSocketData> {
  open: Event;
  message: MessageEvent<Message>;
  close: CloseEvent;
}
/**
 * The handle to a WebSocket client connection: its identity and controls.
 * A handle is what a connection is regardless of where it lives.
 * A `WebSocketClientConnection` is a handle bound to a connection in this
 * process; a handle can also be revived from a serialized connection
 * in another process (e.g. a connection stored by a worker).
 *
 * `Message` is what crosses this connection: raw WebSocket data, or the
 * messages of the extension applied to it.
 */
export declare abstract class WebSocketClientHandle<Message = WebSocketData> {
  abstract id: string;
  abstract url: URL;
  extension?: WebSocketExtension<unknown, unknown>;
  abstract send(data: Message): void;
  abstract close(code?: number, reason?: string): void;
  abstract addEventListener<EventType extends keyof WebSocketClientEventMap<Message>>(type: EventType, listener: WebSocketEventListener<WebSocketClientEventMap<Message>[EventType]>, options?: AddEventListenerOptions | boolean): void;
  abstract removeEventListener<EventType extends keyof WebSocketClientEventMap<Message>>(event: EventType, listener: WebSocketEventListener<WebSocketClientEventMap<Message>[EventType]>, options?: EventListenerOptions | boolean): void;
}
/**
 * The WebSocket client instance represents an incoming
 * client connection. The user can control the connection,
 * send and receive events.
 */
export declare class WebSocketClientConnection<Message = WebSocketData> implements WebSocketClientHandle<Message> {
  #private;
  readonly socket: WebSocket;
  private readonly transport;
  readonly id: string;
  readonly url: URL;
  /**
   * An optional extension applied to the data crossing this connection:
   * `send()` encodes, outgoing client frames are decoded
   * before being dispatched as `message` events.
   */
  extension?: WebSocketExtension<unknown, unknown>;
  /**
   * The intercepted connection this client belongs to.
   * Provided by the interceptor once both connections exist.
   */
  [kExtensionContext]?: WebSocketExtensionContext<unknown>;
  private [kEmitter];
  constructor(socket: WebSocket, transport: WebSocketTransport);
  /**
   * Listen for the outgoing events from the connected WebSocket client.
   */
  addEventListener<EventType extends keyof WebSocketClientEventMap<Message>>(type: EventType, listener: WebSocketEventListener<WebSocketClientEventMap<Message>[EventType]>, options?: AddEventListenerOptions | boolean): void;
  /**
   * Removes the listener for the given event.
   */
  removeEventListener<EventType extends keyof WebSocketClientEventMap<Message>>(event: EventType, listener: WebSocketEventListener<WebSocketClientEventMap<Message>[EventType]>, options?: EventListenerOptions | boolean): void;
  /**
   * Send data to the connected client.
   */
  send(data: Message): void;
  /**
   * Close the WebSocket connection.
   * @param {number} code A status code (see https://www.rfc-editor.org/rfc/rfc6455#section-7.4.1).
   * @param {string} reason A custom connection close reason.
   */
  close(code?: number, reason?: string): void;
}
//#endregion
//#region src/interceptors/WebSocket/index.d.ts
type WebSocketExtensions = ReadonlyArray<WebSocketExtension<unknown, unknown>>;
/**
 * The messages crossing the connections intercepted with the given
 * extensions: the messages of the extension applied to a connection,
 * or raw WebSocket data when there are no extensions.
 *
 * @note The types assume one of the extensions matches the connection.
 */
export type WebSocketInterceptorMessage<Extensions extends WebSocketExtensions> = [Extensions] extends [readonly []] ? WebSocketData : WebSocketExtensionMessage<Extensions[number]>;
/**
 * The API the extension applied to a connection adds to the connection event.
 */
export type WebSocketInterceptorApi<Extensions extends WebSocketExtensions> = [Extensions] extends [readonly []] ? {} : WebSocketExtensionApi<Extensions[number]>;
export interface WebSocketInterceptorOptions<Extensions extends WebSocketExtensions = []> {
  /**
   * Extensions to apply to the intercepted connections.
   * The first extension whose `match()` accepts a connection is applied
   * to it. An extension without `match()` accepts every connection.
   */
  extensions?: Extensions;
}
/**
 * Intercept the outgoing WebSocket connections created using
 * the global `WebSocket` class.
 */
export declare class WebSocketInterceptor<const Extensions extends WebSocketExtensions = []> extends Interceptor<WebSocketEventMap$1<WebSocketInterceptorMessage<Extensions>, WebSocketInterceptorApi<Extensions>>> {
  static symbol: symbol;
  private readonly extensions;
  constructor(options?: WebSocketInterceptorOptions<Extensions>);
  protected predicate(): boolean;
  protected setup(): void;
}
//#endregion
export type { WebSocketClientEventMap, WebSocketConnectionEventData, WebSocketConnectionInfo, WebSocketData, WebSocketEventMap$1 as WebSocketEventMap, WebSocketExtensionApi, WebSocketExtensionContext, WebSocketExtensionMessage, WebSocketExtensionMessageContext, WebSocketExtensionResult, WebSocketInterceptedConnection, WebSocketServerEventMap, WebSocketTransport };
//# sourceMappingURL=index.d.ts.map