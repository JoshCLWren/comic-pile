import { c as isStringEqual, d as getRawSetCookie, h as devUtils, m as InternalError, r as toPublicUrl, t as cookieStore } from "./cookie-store.js";
import { n as getSiblingHandlers, o as kAutoConnect, r as isSiblingHandler, s as kConnect } from "./attach-sibling-handlers.js";
import { t as executeHandlers } from "./execute-handlers.js";
import { isPassthroughResponse } from "../utils/passthrough.js";
import { isCommonAssetRequest } from "../utils/is-common-asset-request.js";
import { invariant } from "outvariant";
import { BatchInterceptor, createRequestId } from "@mswjs/interceptors";
import { Emitter, TypedEvent } from "rettime";
import { until } from "until-async";
//#region src/core/experimental/sources/network-source.ts
var NetworkFrameEvent = class extends TypedEvent {
	frame;
	constructor(type, frame) {
		super(...[type, {}]);
		this.frame = frame;
	}
};
var NetworkSource = class {
	emitter;
	constructor() {
		this.emitter = new Emitter();
	}
	async queue(frame) {
		await this.emitter.emitAsPromise(new NetworkFrameEvent("frame", frame));
	}
	on(type, listener, options) {
		this.emitter.on(type, listener, options);
	}
	disable() {
		this.emitter.removeAllListeners();
	}
};
//#endregion
//#region src/core/experimental/handlers-controller.ts
function addHandlerToGroup(groups, kind, handler) {
	(groups[kind] ||= []).push(handler);
}
function prependHandlersToGroup(groups, kind, overridesForKind) {
	const existingForKind = groups[kind];
	groups[kind] = existingForKind ? [...overridesForKind, ...existingForKind.filter((existingHandler) => {
		return !overridesForKind.includes(existingHandler);
	})] : overridesForKind;
}
function groupHandlersByKind(handlers) {
	const groups = {};
	const visitedHandlers = /* @__PURE__ */ new Set();
	const visit = (handler) => {
		if (visitedHandlers.has(handler)) return;
		visitedHandlers.add(handler);
		addHandlerToGroup(groups, handler.kind, handler);
		for (const sibling of getSiblingHandlers(handler)) visit(sibling);
	};
	for (const handler of handlers) visit(handler);
	return groups;
}
var HandlersController = class {
	getInitialState(initialHandlers) {
		invariant(this.#validateHandlers(initialHandlers), devUtils.formatMessage("Failed to apply given request handlers: invalid input. Did you forget to spread the request handlers Array?"));
		const normalizedInitialHandlers = groupHandlersByKind(initialHandlers);
		return {
			initialHandlers: normalizedInitialHandlers,
			handlers: { ...normalizedInitialHandlers }
		};
	}
	currentHandlers() {
		return Object.values(this.getState().handlers).flat().filter((handler) => handler != null);
	}
	/**
	* Return the list of explicitly registered handlers.
	* Unlike `currentHandlers()`, this excludes sibling handlers,
	* which are an implementation detail (e.g. the WebSocket upgrade
	* handler or the GraphQL subscription transport).
	*/
	listHandlers() {
		return this.currentHandlers().filter((handler) => {
			return !isSiblingHandler(handler);
		});
	}
	/**
	* Return the list of handlers of the given kind.
	*/
	getHandlersByKind(kind) {
		return this.getState().handlers[kind] || [];
	}
	use(nextHandlers) {
		invariant(this.#validateHandlers(nextHandlers), devUtils.formatMessage("[MSW] Failed to call \"use()\" with the given request handlers: invalid input. Did you forget to spread the array of request handlers?"));
		if (nextHandlers.length === 0) return;
		const { handlers } = this.getState();
		const overrides = groupHandlersByKind(nextHandlers);
		if (overrides.request) prependHandlersToGroup(handlers, "request", overrides.request);
		if (overrides.websocket) prependHandlersToGroup(handlers, "websocket", overrides.websocket);
		this.setState({ handlers });
	}
	reset(nextHandlers) {
		invariant(nextHandlers.length > 0 ? this.#validateHandlers(nextHandlers) : true, devUtils.formatMessage("Failed to replace initial handlers during reset: invalid handlers. Did you forget to spread the handlers array?"));
		for (const handler of this.currentHandlers()) handler.reset();
		const { initialHandlers } = this.getState();
		if (nextHandlers.length === 0) {
			this.setState({ handlers: { ...initialHandlers } });
			return;
		}
		const normalizedNextHandlers = groupHandlersByKind(nextHandlers);
		this.setState({
			initialHandlers: normalizedNextHandlers,
			handlers: { ...normalizedNextHandlers }
		});
	}
	restore() {
		for (const handler of this.currentHandlers()) handler.restore();
	}
	dispose() {
		const pendingDisposals = [];
		for (const handler of this.currentHandlers()) {
			const disposal = handler.dispose();
			if (disposal instanceof Promise) pendingDisposals.push(disposal);
		}
		if (pendingDisposals.length > 0) return Promise.all(pendingDisposals).then(() => {});
	}
	#validateHandlers(handlers) {
		return handlers.every((handler) => !Array.isArray(handler));
	}
};
var InMemoryHandlersController = class extends HandlersController {
	#handlers;
	#initialHandlers;
	constructor(initialHandlers) {
		super();
		const initialState = this.getInitialState(initialHandlers);
		this.#initialHandlers = initialState.initialHandlers;
		this.#handlers = initialState.handlers;
	}
	getState() {
		return {
			initialHandlers: this.#initialHandlers,
			handlers: this.#handlers
		};
	}
	setState(nextState) {
		if (nextState.initialHandlers) this.#initialHandlers = nextState.initialHandlers;
		if (nextState.handlers) this.#handlers = nextState.handlers;
	}
};
//#endregion
//#region src/core/utils/internal/to-readonly-array.ts
/**
* Creates an immutable copy of the given array.
*/
function toReadonlyArray(source) {
	const clone = [...source];
	Object.freeze(clone);
	return clone;
}
//#endregion
//#region src/core/utils/internal/disposable.ts
var Disposable = class {
	subscriptions = [];
	dispose() {
		let subscription;
		const errors = [];
		while (subscription = this.subscriptions.shift()) try {
			subscription();
		} catch (error) {
			if (error instanceof Error) errors.push(error);
		}
		if (errors.length > 0) console.error(new AggregateError(errors, devUtils.formatMessage("Failed to dispose of some side effects. This is likely an issue with MSW, please report it on GitHub: https://github.com/mswjs/msw/issues")));
	}
};
//#endregion
//#region src/core/experimental/define-network.ts
function colorlessPromiseAll(values) {
	const promises = [];
	for (const value of values) if (value instanceof Promise) promises.push(value);
	if (promises.length > 0) return Promise.all(promises).then(() => {});
}
let NetworkReadyState = /* @__PURE__ */ function(NetworkReadyState) {
	NetworkReadyState[NetworkReadyState["DISABLED"] = 0] = "DISABLED";
	NetworkReadyState[NetworkReadyState["ENABLED"] = 1] = "ENABLED";
	return NetworkReadyState;
}({});
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
function defineNetwork(options) {
	let readyState = 0;
	const events = new Emitter();
	const disposable = new Disposable();
	const deriveHandlersController = (handlers) => {
		return handlers instanceof HandlersController ? handlers : new InMemoryHandlersController(handlers || []);
	};
	let resolvedOptions = { ...options };
	/**
	* @note Create the handlers controller immediately because
	* certain setup APIs, like `setupServer`, don't await `.enable` (`.listen`).
	*/
	let handlersController = deriveHandlersController(resolvedOptions.handlers);
	return {
		get readyState() {
			return readyState;
		},
		events,
		configure(options) {
			invariant(readyState === 0, "Failed to call \"configure()\" on the network: cannot configure an already enabled network.");
			if (options.handlers && !Object.is(options.handlers, resolvedOptions.handlers)) handlersController = deriveHandlersController(options.handlers);
			resolvedOptions = {
				...resolvedOptions,
				...options
			};
		},
		enable() {
			invariant(readyState === 0, "Failed to call \"enable\" on the network: already enabled");
			readyState = 1;
			/**
			* @note Use a session object scoped to the current "enable()"
			* to prevent "frame.events" listeners from surviving across enable/disable cycles.
			* @see The note about `AbortController` below.
			*/
			const session = { active: true };
			disposable["subscriptions"].push(() => {
				session.active = false;
			});
			return colorlessPromiseAll(resolvedOptions.sources.map((source) => {
				/**
				* @note Preemptively disable the network source before enabling.
				* This intentionally calls only the prototype method that clears the
				* event listeners and nothing else. This prevents the "frame" listeners
				* from accumulating across enable/disable in case the source is a singleton.
				*/
				NetworkSource.prototype.disable.call(source);
				source.on("frame", async ({ frame }) => {
					frame.events.on("*", (event) => {
						/**
						* @note Prevent event forwarding manually and not via an AbortController
						* because certain runtimes, like Cloudflare, throw when referencing an
						* AbortController created in a different context. Bear in mind that the frame
						* events run in the patched request client context while the AbortController
						* is created outside, in the "defineNetwork" closure, which is a test context.
						*/
						if (!session.active) return;
						events.emit(event);
					});
					const handlers = frame.getHandlers(handlersController);
					await frame.resolve(handlers, resolvedOptions.onUnhandledFrame || "warn", resolvedOptions.context);
				});
				return source.enable();
			}));
		},
		disable() {
			invariant(readyState === 1, "Failed to call \"disable\" on the network: already disabled");
			readyState = 0;
			const handlersDisposal = handlersController.dispose();
			disposable.dispose();
			/**
			* @note Tear down the sources synchronously, never behind the
			* handlers disposal. `disable()` is not always awaited (e.g.
			* `server.close()` is synchronous), and a deferred teardown would
			* race any `enable()` that follows, disabling the sources that the
			* new session has just enabled.
			*/
			const sourcesDisposal = colorlessPromiseAll(resolvedOptions.sources.map((source) => source.disable()));
			/**
			* @note Await both disposals so neither rejection goes unobserved.
			* Chaining them would leave the source disposal floating whenever
			* the handlers disposal rejects.
			*/
			return handlersDisposal instanceof Promise ? Promise.all([handlersDisposal, sourcesDisposal]).then(() => {}) : sourcesDisposal;
		},
		use(...handlers) {
			handlersController.use(handlers);
		},
		resetHandlers(...handlers) {
			handlersController.reset(handlers);
		},
		restoreHandlers() {
			handlersController.restore();
		},
		listHandlers() {
			return toReadonlyArray(handlersController.listHandlers());
		}
	};
}
//#endregion
//#region src/core/experimental/frames/network-frame.ts
/**
* The base for the network frames. Extend this abstract class
* to implement custom network frames.
*/
var NetworkFrame = class {
	protocol;
	data;
	events;
	constructor(protocol, data) {
		this.protocol = protocol;
		this.data = data;
		this.events = new Emitter();
	}
};
//#endregion
//#region src/core/utils/request/store-response-cookies.ts
async function storeResponseCookies(request, response) {
	if (cookieStore === null) return;
	for (const responseCookie of getRawSetCookie(response)) await cookieStore.setCookie(responseCookie, request.url);
}
//#endregion
//#region src/core/experimental/request-utils.ts
function shouldBypassRequest(request) {
	return !!request.headers.get("accept")?.includes("msw/passthrough");
}
/**
* Remove the internal passthrough instruction from the request's `Accept` header.
*/
function deleteRequestPassthroughHeader(request) {
	const acceptHeader = request.headers.get("accept");
	/**
	* @note Remove the internal bypass request header.
	* In the browser, this is done by the worker script.
	* In Node.js, it has to be done here.
	*/
	if (acceptHeader) {
		const nextAcceptHeader = acceptHeader.replace(/(,\s+)?msw\/passthrough/, "");
		if (nextAcceptHeader) request.headers.set("accept", nextAcceptHeader);
		else request.headers.delete("accept");
	}
}
//#endregion
//#region src/core/experimental/on-unhandled-frame.ts
async function executeUnhandledFrameHandle(frame, handle) {
	const printStrategyMessage = async (strategy) => {
		if (strategy === "bypass") return;
		const message = await frame.getUnhandledMessage();
		switch (strategy) {
			case "warn": return devUtils.warn("Warning: %s", message);
			case "error": return devUtils.error("Error: %s", message);
		}
	};
	const applyStrategy = async (strategy) => {
		invariant.as(InternalError, strategy === "bypass" || strategy === "warn" || strategy === "error", devUtils.formatMessage("Failed to react to an unhandled network frame: unknown strategy \"%s\". Please provide one of the supported strategies (\"bypass\", \"warn\", \"error\") or a custom callback function as the value of the \"onUnhandledFrame\" option.", strategy));
		if (strategy === "bypass") return;
		await printStrategyMessage(strategy);
		if (strategy === "error") return Promise.reject(new InternalError(devUtils.formatMessage("Cannot bypass a request when using the \"error\" strategy for the \"onUnhandledFrame\" option.")));
	};
	if (typeof handle === "function") return handle({
		frame,
		defaults: {
			warn: printStrategyMessage.bind(null, "warn"),
			/**
			* @note The defaults only print the corresponding messages now.
			* They do not affect the frame resolution (e.g. do not error the frame).
			* That is only for backward compatibility reasons. In the future, these should
			* be an alias to `applyStrategy.bind(null, 'error')` instead.
			*/
			error: printStrategyMessage.bind(null, "error")
		}
	});
	/**
	* Ignore unhandled common HTTP assets.
	* @note Calling this here applies the common assets check
	* only to the scenarios when `onUnhandledFrame` was set to a predefined strategy.
	* When using a custom function, you need to check for common assets manually.
	*/
	if (frame instanceof HttpNetworkFrame && isCommonAssetRequest(frame.data.request)) return;
	return applyStrategy(handle);
}
//#endregion
//#region src/core/experimental/frames/http-frame.ts
var RequestEvent = class extends TypedEvent {
	requestId;
	request;
	constructor(type, data) {
		super(...[type, {}]);
		this.requestId = data.requestId;
		this.request = data.request;
	}
};
var ResponseEvent = class extends TypedEvent {
	requestId;
	request;
	response;
	constructor(type, data) {
		super(...[type, {}]);
		this.requestId = data.requestId;
		this.request = data.request;
		this.response = data.response;
	}
};
var UnhandledExceptionEvent = class extends TypedEvent {
	error;
	requestId;
	request;
	constructor(type, data) {
		super(...[type, {}]);
		this.error = data.error;
		this.requestId = data.requestId;
		this.request = data.request;
	}
};
var HttpNetworkFrame = class extends NetworkFrame {
	constructor(options) {
		const id = options.id || createRequestId();
		super("http", {
			id,
			request: options.request
		});
	}
	getHandlers(controller) {
		return controller.getHandlersByKind("request");
	}
	async getUnhandledMessage() {
		const { request } = this.data;
		const url = new URL(request.url);
		const publicUrl = toPublicUrl(url) + url.search;
		const requestBody = request.body == null ? null : await request.clone().text();
		return `intercepted a request without a matching request handler:${`\n\n  \u2022 ${request.method} ${publicUrl}\n\n${requestBody ? `  \u2022 Request body: ${requestBody}\n\n` : ""}`}If you still wish to intercept this unhandled request, please create a request handler for it.\nRead more: https://mswjs.io/docs/http/intercepting-requests`;
	}
	async resolve(handlers, onUnhandledFrame, resolutionContext) {
		const { id: requestId, request } = this.data;
		const requestCloneForLogs = resolutionContext?.quiet ? null : request.clone();
		this.events.emit(new RequestEvent("request:start", {
			requestId,
			request
		}));
		if (shouldBypassRequest(request)) {
			this.events.emit(new RequestEvent("request:end", {
				requestId,
				request
			}));
			this.passthrough();
			return null;
		}
		const [lookupError, lookupResult] = await until(() => {
			return executeHandlers({
				requestId,
				request,
				handlers,
				resolutionContext: {
					baseUrl: resolutionContext?.baseUrl?.toString(),
					quiet: resolutionContext?.quiet
				}
			});
		});
		if (lookupError != null) {
			if (!this.events.emit(new UnhandledExceptionEvent("unhandledException", {
				error: lookupError,
				requestId,
				request
			}))) {
				console.error(lookupError);
				devUtils.error("Encountered an unhandled exception during the handler lookup for \"%s %s\". Please see the original error above.", request.method, request.url);
			}
			this.errorWith(lookupError);
			return null;
		}
		if (lookupResult == null) {
			/**
			* @note Unhandled CONNECT requests establish a tunnel through a proxy.
			* They are transport, not the request the developer cares about, so
			* they pass through silently regardless of the unhandled frame strategy.
			* The request sent through the tunnel gets its own resolution.
			*/
			if (isStringEqual(request.method, "CONNECT")) {
				this.events.emit(new RequestEvent("request:end", {
					requestId,
					request
				}));
				this.passthrough();
				return null;
			}
			this.events.emit(new RequestEvent("request:unhandled", {
				requestId,
				request
			}));
			/**
			* @note The unhandled frame handle must be executed during the request resolution
			* since it can influence it (e.g. error the request if the "error" startegy was used).
			*/
			await executeUnhandledFrameHandle(this, onUnhandledFrame).then(() => this.passthrough(), (error) => this.errorWith(error));
			this.events.emit(new RequestEvent("request:end", {
				requestId,
				request
			}));
			return false;
		}
		const { response, handler, parsedResult } = lookupResult;
		this.events.emit(new RequestEvent("request:match", {
			requestId,
			request
		}));
		if (response == null) {
			this.events.emit(new RequestEvent("request:end", {
				requestId,
				request
			}));
			this.passthrough();
			return null;
		}
		if (isPassthroughResponse(response)) {
			this.events.emit(new RequestEvent("request:end", {
				requestId,
				request
			}));
			this.passthrough();
			return null;
		}
		const responseCloneForLogs = resolutionContext?.quiet ? null : response.clone();
		await storeResponseCookies(request, response);
		this.respondWith(response);
		this.events.emit(new RequestEvent("request:end", {
			requestId,
			request
		}));
		if (!resolutionContext?.quiet) handler.log({
			request: requestCloneForLogs,
			response: responseCloneForLogs,
			parsedResult
		});
		return true;
	}
};
//#endregion
//#region src/core/experimental/frames/websocket-frame.ts
var WebSocketConnectionEvent = class extends TypedEvent {
	url;
	protocols;
	constructor(type, data) {
		super(...[type, {}]);
		this.url = data.url;
		this.protocols = data.protocols;
	}
};
var WebSocketErrorEvent = class extends WebSocketConnectionEvent {
	error;
	constructor(type, data) {
		super(type, data);
		this.error = data.error;
	}
};
var WebSocketNetworkFrame = class extends NetworkFrame {
	constructor(options) {
		super("ws", { connection: options.connection });
	}
	getHandlers(controller) {
		return controller.getHandlersByKind("websocket");
	}
	async resolve(handlers, onUnhandledFrame, resolutionContext) {
		const { connection } = this.data;
		this.events.emit(new WebSocketConnectionEvent("websocket:connection", {
			url: connection.client.url,
			protocols: connection.info.protocols
		}));
		const handleSocketError = (event) => {
			this.events.emit(new WebSocketErrorEvent("websocket:error", {
				url: connection.client.url,
				protocols: connection.info.protocols,
				error: getErrorFromEvent(event)
			}));
		};
		connection.client.socket.addEventListener("error", handleSocketError);
		connection.client.socket.addEventListener("close", () => {
			connection.client.socket.removeEventListener("error", handleSocketError);
		}, { once: true });
		if (handlers.length === 0) {
			await executeUnhandledFrameHandle(this, onUnhandledFrame).then(() => this.passthrough(), (error) => this.errorWith(error));
			return false;
		}
		let hasMatchingHandlers = false;
		for (const handler of handlers) {
			const handlerConnection = await handler.run(connection, {
				baseUrl: resolutionContext?.baseUrl?.toString(),
				/**
				* @note Expose an emit-only reference to this frame's events
				* so the handlers can emit additional events not covered by
				* the frame (e.g. "graphql:subscription").
				*/
				events: this.events,
				/**
				* @note Do not emit the handler's "connection" event when running the handler.
				* Use the run only to get the resolved connection object.
				*/
				[kAutoConnect]: false
			});
			if (!handlerConnection) continue;
			hasMatchingHandlers = true;
			/**
			* @note Attach the WebSocket logger *before* emitting the handler's "connection" event.
			* Connection event listeners may perform actions that should be reflected in the logs
			* (e.g. closing the connection immediately). If the logger is attached after the connection,
			* those actions cannot be properly logged.
			*/
			const removeLogger = !resolutionContext?.quiet ? handler.log(connection) : void 0;
			try {
				if (!handler[kConnect](handlerConnection)) removeLogger?.();
			} catch (error) {
				if (!this.events.emit(new WebSocketErrorEvent("unhandledException", {
					error,
					url: connection.client.url,
					protocols: connection.info.protocols
				}))) {
					console.error(error);
					devUtils.error("Encountered an unhandled exception during the handler lookup for \"%s\". Please see the original error above.", connection.client.url);
				}
				/**
				* @note Throw the caught error so it gets picked up by WebSocketInterceptor.
				* It's the interceptor who translates handler errors to WebSocket closures.
				*/
				throw error;
			}
		}
		if (!hasMatchingHandlers) {
			await executeUnhandledFrameHandle(this, onUnhandledFrame).then(() => this.passthrough(), (error) => this.errorWith(error));
			return false;
		}
		return true;
	}
	async getUnhandledMessage() {
		const { connection } = this.data;
		return `intercepted a WebSocket connection without a matching event handler:${`\n\n  \u2022 ${connection.client.url}\n\n`}If you still wish to intercept this unhandled connection, please create an event handler for it.\nRead more: https://mswjs.io/docs/websocket`;
	}
};
/**
* Extract the error from the given "error" event, if any.
* Supports both the `ErrorEvent.error` property and the `cause`
* property that MSW sets when erroring the connection itself.
*/
function getErrorFromEvent(event) {
	if ("error" in event && event.error != null) return event.error;
	if ("cause" in event && event.cause != null) return event.cause;
}
//#endregion
//#region src/core/experimental/sources/interceptor-source.ts
/**
* Create a network source from the given list of interceptors.
*/
var InterceptorSource = class extends NetworkSource {
	#interceptor;
	/**
	* @note Frames are keyed by the request instance, not the request ID.
	* The interceptor emits the same request instance on the "request"
	* and "response" events, so the frame can be looked up by identity.
	* A weak reference lets the frame be garbage collected alongside
	* its request once the request settles without producing a response
	* (e.g. a passthrough request failing with a network error).
	* @see https://github.com/mswjs/msw/issues/2792
	*/
	#frames;
	constructor(options) {
		super();
		this.#interceptor = new BatchInterceptor({
			name: "interceptor-source",
			interceptors: options.interceptors
		});
		this.#frames = /* @__PURE__ */ new WeakMap();
	}
	enable() {
		this.#interceptor.apply();
		this.#interceptor.on("request", this.#handleRequest.bind(this)).on("response", this.#handleResponse.bind(this)).on("connection", this.#handleWebSocketConnection.bind(this));
	}
	disable() {
		super.disable();
		this.#interceptor.dispose();
		/**
		* @todo We can also abort any pending frames here, given we implement
		* the `NetworkFrame.abort()` method.
		*/
		this.#frames = /* @__PURE__ */ new WeakMap();
	}
	async #handleRequest(event) {
		const { requestId, request, controller } = event;
		const httpFrame = new InterceptorHttpNetworkFrame({
			id: requestId,
			request,
			controller
		});
		this.#frames.set(request, httpFrame);
		await this.queue(httpFrame);
	}
	async #handleResponse({ requestId, request, response, responseType }) {
		const httpFrame = this.#frames.get(request);
		this.#frames.delete(request);
		if (httpFrame == null) return;
		queueMicrotask(() => {
			try {
				httpFrame.events.emit(new ResponseEvent(responseType === "mock" ? "response:mocked" : "response:bypass", {
					requestId,
					request,
					response
				}));
			} finally {
				/**
				* @note Remove any listeners from this frame.
				* Past this point, it won't emit anything. The removal is crucial
				* to prevent "rettime" from keeping the abort cleanup listeners internally.
				* @see https://github.com/mswjs/msw/issues/2735
				*/
				httpFrame.events.removeAllListeners();
			}
		});
	}
	async #handleWebSocketConnection(connection) {
		await this.queue(new InterceptorWebSocketNetworkFrame({ connection }));
	}
};
var InterceptorHttpNetworkFrame = class extends HttpNetworkFrame {
	#controller;
	constructor(options) {
		super({
			id: options.id,
			request: options.request
		});
		this.#controller = options.controller;
	}
	passthrough() {
		deleteRequestPassthroughHeader(this.data.request);
	}
	respondWith(response) {
		if (response) this.#controller.respondWith(response);
	}
	errorWith(reason) {
		if (reason instanceof Response) return this.respondWith(reason);
		if (reason instanceof InternalError) this.#controller.errorWith(reason);
		throw reason;
	}
};
var InterceptorWebSocketNetworkFrame = class extends WebSocketNetworkFrame {
	/**
	* The in-process client connection, whose socket
	* the frame dispatches errors on.
	*/
	#client;
	constructor(args) {
		super({ connection: args.connection });
		this.#client = args.connection.client;
		/**
		* @note Provide a similar frame listener cleanup as for HTTP.
		* When the client connection closes, the handler can no longer be used.
		*/
		args.connection.client.addEventListener("close", () => {
			this.events.removeAllListeners();
		}, { once: true });
	}
	errorWith(reason) {
		if (reason instanceof Error) {
			/**
			* Use `client.errorWith(reason)` in the future.
			* @see https://github.com/mswjs/interceptors/issues/747
			*/
			const errorEvent = new Event("error");
			Object.defineProperty(errorEvent, "cause", {
				enumerable: true,
				configurable: false,
				value: reason
			});
			this.#client.socket.dispatchEvent(errorEvent);
		}
	}
	passthrough() {
		this.data.connection.server.connect();
	}
};
//#endregion
export { NetworkFrame as a, HandlersController as c, ResponseEvent as i, InMemoryHandlersController as l, WebSocketNetworkFrame as n, NetworkReadyState as o, HttpNetworkFrame as r, defineNetwork as s, InterceptorSource as t, NetworkSource as u };

//# sourceMappingURL=interceptor-source.js.map