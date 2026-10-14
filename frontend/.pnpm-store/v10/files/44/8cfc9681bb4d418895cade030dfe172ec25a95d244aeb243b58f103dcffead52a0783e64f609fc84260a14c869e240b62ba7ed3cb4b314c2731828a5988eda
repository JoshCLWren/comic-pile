import { _ as Handler, a as matchRequestUrl, g as getCallFrame, h as devUtils, o as isAbsoluteUrl, r as toPublicUrl, s as getTimestamp } from "./cookie-store.js";
import { t as isObject } from "./is-object.js";
import { t as colors } from "./colors.js";
import { invariant } from "outvariant";
import { createRequestId, resolveWebSocketUrl } from "@mswjs/interceptors";
import { Emitter, TypedEvent } from "rettime";
import { WebSocketClientConnection, WebSocketServerConnection } from "@mswjs/interceptors/WebSocket";
//#region src/ws/utils/get-message-length.ts
/**
* Returns the byte length of the given WebSocket message.
* @example
* getMessageLength('hello') // 5
* getMessageLength(new Blob(['hello'])) // 5
*/
function getMessageLength(data) {
	if (data instanceof Blob) return data.size;
	if (isObject(data) && "byteLength" in data) return data.byteLength;
	return new Blob([data]).size;
}
//#endregion
//#region src/ws/utils/truncate-message.ts
const MAX_LENGTH = 24;
function truncateMessage(message) {
	if (message.length <= MAX_LENGTH) return message;
	return `${message.slice(0, MAX_LENGTH)}…`;
}
//#endregion
//#region src/ws/utils/get-public-data.ts
/**
* Format the given WebSocket data or protocol message for logging.
*/
async function getPublicData(data) {
	if (typeof data === "string") return truncateMessage(data);
	if (data instanceof Blob) return `Blob(${truncateMessage(await data.text())})`;
	if (data instanceof ArrayBuffer || ArrayBuffer.isView(data)) return `ArrayBuffer(${truncateMessage(new TextDecoder().decode(data))})`;
	return truncateMessage(JSON.stringify(data));
}
//#endregion
//#region src/ws/utils/attach-websocket-logger.ts
function attachWebSocketLogger(connection) {
	const { client, server } = connection;
	const controller = new AbortController();
	logConnectionOpen(client);
	/**
	* @todo Provide the reference to the exact event handler
	* that called this `client.send()`.
	*/
	client.addEventListener("message", (event) => {
		logOutgoingClientMessage(event);
	}, { signal: controller.signal });
	client.addEventListener("close", (event) => {
		logConnectionClose(event);
	}, { signal: controller.signal });
	getClientSocket(client)?.addEventListener("error", (event) => {
		logClientError(event);
	}, { signal: controller.signal });
	const { send: originalClientSend } = client;
	client.send = new Proxy(client.send, { apply(target, thisArg, args) {
		const [data] = args;
		const messageEvent = new MessageEvent("message", { data });
		Object.defineProperties(messageEvent, {
			currentTarget: {
				enumerable: true,
				writable: false,
				value: getClientSocket(client)
			},
			target: {
				enumerable: true,
				writable: false,
				value: getClientSocket(client)
			}
		});
		queueMicrotask(() => {
			logIncomingMockedClientMessage(messageEvent);
		});
		return Reflect.apply(target, thisArg, args);
	} });
	server.addEventListener("open", () => {
		server.addEventListener("message", (event) => {
			logIncomingServerMessage(event);
		});
	}, {
		once: true,
		signal: controller.signal
	});
	const { send: originalServerSend } = server;
	server.send = new Proxy(server.send, { apply(target, thisArg, args) {
		const [data] = args;
		const messageEvent = new MessageEvent("message", { data });
		Object.defineProperties(messageEvent, {
			currentTarget: {
				enumerable: true,
				writable: false,
				value: getServerSocket(server)
			},
			target: {
				enumerable: true,
				writable: false,
				value: getServerSocket(server)
			}
		});
		logOutgoingMockedClientMessage(messageEvent);
		return Reflect.apply(target, thisArg, args);
	} });
	controller.signal.addEventListener("abort", () => {
		client.send = originalClientSend;
		server.send = originalServerSend;
	}, { once: true });
	return () => {
		controller.abort();
	};
}
/**
* Prints the WebSocket connection.
* This is meant to be logged by every WebSocket handler
* that intercepted this connection. This helps you see
* what handlers observe this connection.
*/
function logConnectionOpen(client) {
	const publicUrl = toPublicUrl(client.url);
	console.groupCollapsed(devUtils.formatMessage(`${getTimestamp()} %c▶%c ${publicUrl}`), `color:${colors.system}`, "color:inherit");
	console.log("Client:", getClientSocket(client) ?? client);
	console.groupEnd();
}
/**
* Return the underlying `WebSocket` of the given client, if any.
* Only in-process client connections are backed by a socket;
* a handle to a connection elsewhere (e.g. another runtime) is not.
*/
function getClientSocket(client) {
	if (client instanceof WebSocketClientConnection) return client.socket;
}
/**
* Return the underlying `WebSocket` of the given server, if any.
* Only in-process server connections are backed by a socket.
*/
function getServerSocket(server) {
	if (server instanceof WebSocketServerConnection) return server.socket;
}
function logConnectionClose(event) {
	const target = event.target;
	const publicUrl = toPublicUrl(target.url);
	console.groupCollapsed(devUtils.formatMessage(`${getTimestamp({ milliseconds: true })} %c■%c ${publicUrl}`), `color:${colors.system}`, "color:inherit");
	console.log(event);
	console.groupEnd();
}
function logClientError(event) {
	const socket = event.target;
	const publicUrl = toPublicUrl(socket.url);
	console.groupCollapsed(devUtils.formatMessage(`${getTimestamp({ milliseconds: true })} %c\u00D7%c ${publicUrl}`), `color:${colors.system}`, "color:inherit");
	console.log(event);
	console.groupEnd();
}
/**
* Prints the outgoing client message.
*/
async function logOutgoingClientMessage(event) {
	const byteLength = getMessageLength(event.data);
	const publicData = await getPublicData(event.data);
	const arrow = event.defaultPrevented ? "⇡" : "⬆";
	console.groupCollapsed(devUtils.formatMessage(`${getTimestamp({ milliseconds: true })} %c${arrow}%c ${publicData} %c${byteLength}%c`), `color:${colors.outgoing}`, "color:inherit", "color:gray;font-weight:normal", "color:inherit;font-weight:inherit");
	console.log(event);
	console.groupEnd();
}
/**
* Prints the outgoing client message initiated
* by `server.send()` in the event handler.
*/
async function logOutgoingMockedClientMessage(event) {
	const byteLength = getMessageLength(event.data);
	const publicData = await getPublicData(event.data);
	console.groupCollapsed(devUtils.formatMessage(`${getTimestamp({ milliseconds: true })} %c⬆%c ${publicData} %c${byteLength}%c`), `color:${colors.mocked}`, "color:inherit", "color:gray;font-weight:normal", "color:inherit;font-weight:inherit");
	console.log(event);
	console.groupEnd();
}
/**
* Prints the outgoing client message initiated
* by `client.send()` in the event handler.
*/
async function logIncomingMockedClientMessage(event) {
	const byteLength = getMessageLength(event.data);
	const publicData = await getPublicData(event.data);
	console.groupCollapsed(devUtils.formatMessage(`${getTimestamp({ milliseconds: true })} %c⬇%c ${publicData} %c${byteLength}%c`), `color:${colors.mocked}`, "color:inherit", "color:gray;font-weight:normal", "color:inherit;font-weight:inherit");
	console.log(event);
	console.groupEnd();
}
async function logIncomingServerMessage(event) {
	const byteLength = getMessageLength(event.data);
	const publicData = await getPublicData(event.data);
	const arrow = event.defaultPrevented ? "⇣" : "⬇";
	console.groupCollapsed(devUtils.formatMessage(`${getTimestamp({ milliseconds: true })} %c${arrow}%c ${publicData} %c${byteLength}%c`), `color:${colors.incoming}`, "color:inherit", "color:gray;font-weight:normal", "color:inherit;font-weight:inherit");
	console.log(event);
	console.groupEnd();
}
//#endregion
//#region src/ws/websocket-handler.ts
var WebSocketConnectionEvent = class extends TypedEvent {
	client;
	server;
	info;
	params;
	constructor(connection) {
		super("connection");
		this.client = connection.client;
		this.server = connection.server;
		this.info = connection.info;
		this.params = connection.params;
	}
};
const kEmitter = Symbol("kEmitter");
const kConnect = Symbol("kConnect");
const kAutoConnect = Symbol("kAutoConnect");
const kStopPropagationPatched = Symbol("kStopPropagationPatched");
const KOnStopPropagation = Symbol("KOnStopPropagation");
var WebSocketHandler = class extends Handler {
	url;
	id;
	callFrame;
	kind = "websocket";
	[kEmitter];
	extensions;
	constructor(url, options) {
		super();
		this.url = url;
		this.id = createRequestId();
		this.extensions = options?.extensions ?? [];
		this[kEmitter] = new Emitter();
		this.callFrame = getCallFrame(/* @__PURE__ */ new Error());
	}
	parse(args) {
		const clientUrl = new URL(args.url);
		const resolvedHandlerUrl = this.url instanceof RegExp || isAbsoluteUrl(this.url) || this.url.startsWith("*") ? this.url : this.#resolveWebSocketUrl(this.url, args.resolutionContext?.baseUrl);
		/**
		* @note Remove the Socket.IO path prefix from the WebSocket
		* client URL. This is an exception to keep the users from
		* including the implementation details in their handlers.
		*/
		clientUrl.pathname = clientUrl.pathname.replace(/^\/socket.io\//, "/");
		return { match: matchRequestUrl(clientUrl, resolvedHandlerUrl, args.resolutionContext?.baseUrl) };
	}
	predicate(args) {
		return args.parsedResult.match.matches;
	}
	test(url, resolutionContext) {
		return this.#match(url, resolutionContext) != null;
	}
	async run(connection, resolutionContext) {
		const parsedResult = this.#match(connection.client.url, resolutionContext);
		if (parsedResult == null) return null;
		for (const extension of this.extensions) extension.apply(connection);
		/**
		* @note Expose the extensions' own APIs (e.g. rooms) on the connection
		* event, merged left to right. The link infers the merged type from the
		* extensions it was given; `Object.assign` with a spread of sources is
		* untyped, which is what allows the merged value to take that type.
		*/
		const resolvedConnection = Object.assign({
			client: connection.client,
			server: connection.server,
			info: connection.info,
			params: parsedResult.match.params || {}
		}, ...this.extensions.map((extension) => extension.extend?.(connection)));
		if (resolutionContext?.[kAutoConnect] ?? true) {
			if (this[kConnect](resolvedConnection)) return resolvedConnection;
			return null;
		}
		return resolvedConnection;
	}
	#match(url, resolutionContext) {
		const resolvedUrl = this.#resolveWebSocketUrl(url.toString(), resolutionContext?.baseUrl);
		const parsedResult = this.parse({
			url: resolvedUrl,
			resolutionContext
		});
		if (this.predicate({
			url,
			parsedResult
		})) return parsedResult;
		return null;
	}
	[kConnect](connection) {
		connection.client.addEventListener("message", createStopPropagationListener(this));
		connection.client.addEventListener("close", createStopPropagationListener(this));
		connection.server.addEventListener("open", createStopPropagationListener(this));
		connection.server.addEventListener("message", createStopPropagationListener(this));
		connection.server.addEventListener("error", createStopPropagationListener(this));
		connection.server.addEventListener("close", createStopPropagationListener(this));
		/**
		* @fixme Await these events (e.g. via `.emitAsPromise()`) to have
		* exceptions from asynchronous listeners propagate properly.
		*/
		return this[kEmitter].emit(Object.assign(new WebSocketConnectionEvent(connection), connection));
	}
	log(connection) {
		return attachWebSocketLogger(connection);
	}
	#resolveWebSocketUrl(url, baseUrl) {
		/**
		* @note Omit the trailing slash.
		* While the browser always produces a trailing slash at the end of a WebSocket URL,
		* having it in as the handler's predicate would mean it is *required* in the actual URL.
		*/
		return resolveWebSocketUrl(baseUrl ? new URL(url, baseUrl) : url).replace(/\/$/, "");
	}
};
function createStopPropagationListener(handler) {
	return function stopPropagationListener(event) {
		const propagationStoppedAt = Reflect.get(event, "kPropagationStoppedAt");
		if (propagationStoppedAt && handler.id !== propagationStoppedAt) {
			event.stopImmediatePropagation();
			return;
		}
		Object.defineProperty(event, KOnStopPropagation, {
			value() {
				Object.defineProperty(event, "kPropagationStoppedAt", { value: handler.id });
			},
			configurable: true
		});
		if (!Reflect.get(event, kStopPropagationPatched)) {
			event.stopPropagation = new Proxy(event.stopPropagation, { apply: (target, thisArg, args) => {
				Reflect.get(event, KOnStopPropagation)?.call(handler);
				return Reflect.apply(target, thisArg, args);
			} });
			Object.defineProperty(event, kStopPropagationPatched, {
				value: true,
				configurable: false
			});
		}
	};
}
//#endregion
//#region src/core/utils/internal/attach-sibling-handlers.ts
const kSiblingHandlers = Symbol("kSiblingHandlers");
const kIsSiblingHandler = Symbol("kIsSiblingHandler");
function attachSiblingHandlers(owner, siblings) {
	invariant(getSiblingHandlers(owner).length === 0, "Failed to merge handlers: the owner \"%s\" handler is already merged", owner.kind);
	Object.defineProperty(owner, kSiblingHandlers, {
		value: siblings,
		enumerable: false,
		writable: false,
		configurable: false
	});
	for (const sibling of siblings) if (!isSiblingHandler(sibling)) Object.defineProperty(sibling, kIsSiblingHandler, {
		value: true,
		enumerable: false,
		writable: false,
		configurable: false
	});
	return owner;
}
function getSiblingHandlers(owner) {
	return Reflect.get(owner, kSiblingHandlers) || [];
}
function isSiblingHandler(handler) {
	return Reflect.get(handler, kIsSiblingHandler) === true;
}
//#endregion
export { WebSocketHandler as a, kEmitter as c, WebSocketConnectionEvent as i, getSiblingHandlers as n, kAutoConnect as o, isSiblingHandler as r, kConnect as s, attachSiblingHandlers as t };

//# sourceMappingURL=attach-sibling-handlers.js.map