import { h as devUtils } from "../_chunks/cookie-store.js";
import { c as HandlersController, s as defineNetwork, t as InterceptorSource } from "../_chunks/interceptor-source.js";
import { invariant } from "outvariant";
import { WebSocketInterceptor } from "@mswjs/interceptors/WebSocket";
import { ClientRequestInterceptor } from "@mswjs/interceptors/ClientRequest";
import { XMLHttpRequestInterceptor } from "@mswjs/interceptors/XMLHttpRequest";
import { FetchInterceptor } from "@mswjs/interceptors/fetch";
import { AsyncLocalStorage } from "node:async_hooks";
//#region src/node/async-handlers-controller.ts
var AsyncHandlersController = class extends HandlersController {
	#asyncContext;
	#fallbackContext;
	constructor(initialHandlers) {
		super();
		const initialState = this.getInitialState(initialHandlers);
		this.#asyncContext = new AsyncLocalStorage();
		this.#fallbackContext = {
			initialHandlers: initialState.initialHandlers,
			handlers: initialState.handlers
		};
	}
	getState() {
		const { initialHandlers, handlers } = this.#getContext();
		return {
			initialHandlers,
			handlers
		};
	}
	setState(nextState) {
		const context = this.#getContext();
		if (nextState.initialHandlers) context.initialHandlers = nextState.initialHandlers;
		if (nextState.handlers) context.handlers = nextState.handlers;
	}
	boundary(callback) {
		return (...args) => {
			const initialHandlers = { ...this.getState().handlers };
			return this.#asyncContext.run({
				initialHandlers,
				handlers: { ...initialHandlers }
			}, callback, ...args);
		};
	}
	#getContext() {
		return this.#asyncContext.getStore() || this.#fallbackContext;
	}
};
//#endregion
//#region src/node/setup-server-common.ts
/**
* Define the common `setupServer` API around the given network,
* including the baseline setup methods, like `.use()`, `.resetHandlers()`, `.close()`, etc.
*/
function defineSetupServerApi(network) {
	return {
		get readyState() {
			return network.readyState;
		},
		events: network.events,
		listen(options) {
			invariant(network.readyState === 0, devUtils.formatMessage("Failed to call \"server.listen()\": the server is already listening. Remove the redundant \"server.listen()\" call."));
			network.configure({ onUnhandledFrame: options?.onUnhandledFrame ?? "warn" });
			network.enable();
		},
		use: network.use.bind(network),
		resetHandlers: network.resetHandlers.bind(network),
		restoreHandlers: network.restoreHandlers.bind(network),
		listHandlers: network.listHandlers.bind(network),
		close() {
			network.disable();
		}
	};
}
//#endregion
//#region src/node/setup-server.ts
const defaultInterceptors = [
	new ClientRequestInterceptor(),
	new XMLHttpRequestInterceptor(),
	new FetchInterceptor(),
	new WebSocketInterceptor()
];
const defaultNetworkOptions = {
	sources: [new InterceptorSource({ interceptors: defaultInterceptors })],
	onUnhandledFrame: "warn",
	context: { quiet: true }
};
/**
* Enables request interception in Node.js with the given request handlers.
* @see {@link https://mswjs.io/docs/api/setup-server `setupServer()` API reference}
*/
function setupServer(...handlers) {
	const handlersController = new AsyncHandlersController(handlers);
	const network = defineNetwork({
		...defaultNetworkOptions,
		handlers: handlersController
	});
	return {
		...defineSetupServerApi(network),
		/**
		* @note Spreading evaluates the "readyState" getter once.
		* Redefine it so the property stays live.
		*/
		get readyState() {
			return network.readyState;
		},
		boundary: handlersController.boundary.bind(handlersController)
	};
}
//#endregion
export { AsyncHandlersController, defaultNetworkOptions, setupServer };

//# sourceMappingURL=index.js.map