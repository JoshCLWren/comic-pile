import { b as UnionToIntersection } from "./request-handler.js";
import { c as WebSocketHandler, o as AnyWebSocketExtension, u as WebSocketHandlerEventMap } from "./handlers-controller.js";
import { n as Path, r as PathParams } from "./match-request-url.js";
import { EventMap } from "rettime";
import { WebSocketClientHandle, WebSocketData as WebSocketData$1, WebSocketExtension, WebSocketExtensionApi, WebSocketExtensionMessage } from "@mswjs/interceptors/WebSocket";
//#region src/ws/ws.d.ts
type WebSocketEventListener<EventType extends keyof WebSocketHandlerEventMap, Extension extends AnyWebSocketExtension = WebSocketExtension> = EventMap.Listener<WebSocketHandlerEventMap<Extension>, EventType>;
type WebSocketExtensions = ReadonlyArray<AnyWebSocketExtension>;
/**
 * The messages and the API of each extension, boxed one extension at a
 * time. Intersecting the boxes intersects the values of different
 * extensions only, so a value that is itself a union (e.g. a message
 * union) stays intact.
 */
type BoxedExtension<Extension> = Extension extends unknown ? {
  message: WebSocketExtensionMessage<Extension>;
  api: WebSocketExtensionApi<Extension>;
} : never;
type MergedExtension<Extension, Fallback extends {
  message: unknown;
  api: unknown;
}> = [Extension] extends [never] ? Fallback : UnionToIntersection<BoxedExtension<Extension>>;
/**
 * The extensions of a link merged into a single extension:
 * the connections speak the messages of every extension, and the
 * connection event carries the APIs of every extension. A link
 * without extensions speaks raw WebSocket data.
 */
type WebSocketLinkExtension<Extensions extends WebSocketExtensions> = MergedExtension<Extensions[number], {
  message: WebSocketData$1;
  api: {};
}> extends (infer Merged extends {
  message: unknown;
  api: unknown;
}) ? WebSocketExtension<Merged['message'], Merged['api']> : never;
interface WebSocketLinkOptions<Extensions extends WebSocketExtensions = []> {
  /**
   * Extensions applied to every connection intercepted by this link,
   * left to right. Encoding and decoding happen behind the scenes:
   * `client.send()`, `server.send()`, `broadcast()`, and the `message`
   * events all operate on the extensions' messages, and each extension's
   * own API is exposed on the connection event.
   *
   * @example
   * const chat = ws.link('wss://chat.example.com', { extensions: [new SocketIo()] })
   * chat.addEventListener('connection', ({ client, rooms }) => {
   *   client.send({ event: 'greeting', args: ['hello'] })
   * })
   */
  extensions?: Extensions;
}
type WebSocketLink<Extension extends AnyWebSocketExtension = WebSocketExtension> = {
  /**
   * A set of all WebSocket clients connected
   * to this link.
   *
   * @see {@link https://mswjs.io/docs/api/ws#clients `clients` API reference}
   */
  clients: Set<WebSocketClientHandle<WebSocketExtensionMessage<Extension>>>;
  /**
   * Adds an event listener to this WebSocket link.
   *
   * @example
   * const chat = ws.link('wss://chat.example.com')
   * chat.addEventListener('connection', listener)
   *
   * @see {@link https://mswjs.io/docs/api/ws#onevent-listener `on()` API reference}
   */
  addEventListener: <EventType extends keyof WebSocketHandlerEventMap>(event: EventType, listener: WebSocketEventListener<EventType, Extension>) => WebSocketHandler<Extension>;
  /**
   * Broadcasts the given data to all WebSocket clients.
   *
   * @example
   * const service = ws.link('wss://example.com')
   * service.addEventListener('connection', () => {
   *   service.broadcast('hello, everyone!')
   * })
   *
   * @see {@link https://mswjs.io/docs/api/ws#broadcastdata `broadcast()` API reference}
   */
  broadcast: (data: WebSocketExtensionMessage<Extension>) => void;
  /**
   * Broadcasts the given data to all WebSocket clients
   * except the ones provided in the `clients` argument.
   *
   * @example
   * const service = ws.link('wss://example.com')
   * service.addEventListener('connection', ({ client }) => {
   *   service.broadcastExcept(client, 'hi, the rest of you!')
   * })
   *
   * @see {@link https://mswjs.io/docs/api/ws#broadcastexceptclients-data `broadcast()` API reference}
   */
  broadcastExcept: (clients: WebSocketClientHandle<WebSocketExtensionMessage<Extension>> | Array<WebSocketClientHandle<WebSocketExtensionMessage<Extension>>>, data: WebSocketExtensionMessage<Extension>) => void;
};
/**
 * Intercepts outgoing WebSocket connections to the given URL.
 *
 * @example
 * const chat = ws.link('wss://chat.example.com')
 * chat.addEventListener('connection', ({ client }) => {
 *   client.send('hello from server!')
 * })
 */
declare function createWebSocketLinkHandler<const Extensions extends WebSocketExtensions = []>(url: Path, options?: WebSocketLinkOptions<Extensions>): WebSocketLink<WebSocketLinkExtension<Extensions>>;
interface WebSocketNamespace {
  link: typeof createWebSocketLinkHandler;
  /**
   * Request handler for the `upgrade` requests to the WebSocket protocol.
   * This requires a WebSocket handler to be present to fire.
   * @note This only affects Node.js as the `upgrade` request header is
   * forbidden and cannot be read in the browser. Consider using the
   * `WebSocket` API for establishing WebSocket connections in the browser.
   */
  onUpgrade: (info: {
    requestId: string;
    request: Request;
    params: PathParams;
  }) => Promise<Response | undefined> | Response | undefined;
}
/**
 * A namespace to intercept and mock WebSocket connections.
 *
 * @example
 * const chat = ws.link('wss://chat.example.com')
 *
 * @see {@link https://mswjs.io/docs/api/ws `ws` API reference}
 * @see {@link https://mswjs.io/docs/basics/handling-websocket-events Handling WebSocket events}
 */
declare const ws: WebSocketNamespace;
//#endregion
export { WebSocketLinkOptions as a, WebSocketLinkExtension as i, WebSocketEventListener as n, ws as o, WebSocketLink as r, WebSocketData$1 as t };
//# sourceMappingURL=ws.d.ts.map