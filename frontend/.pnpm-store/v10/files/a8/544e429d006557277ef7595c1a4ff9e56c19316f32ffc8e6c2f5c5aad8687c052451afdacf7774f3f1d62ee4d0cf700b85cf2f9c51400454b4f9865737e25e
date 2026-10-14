import { h as devUtils } from "../_chunks/cookie-store.js";
import { t as RequestHandler } from "../_chunks/request-handler.js";
import { t as isObject } from "../_chunks/is-object.js";
import { t as HttpResponse } from "../_chunks/http-response.js";
import { i as ResponseEvent, r as HttpNetworkFrame, s as defineNetwork, t as InterceptorSource, u as NetworkSource } from "../_chunks/interceptor-source.js";
import { isNodeProcess } from "is-node-process";
import { invariant } from "outvariant";
import { FetchRequest, FetchResponse } from "@mswjs/interceptors";
import { Emitter, TypedEvent } from "rettime";
import { WebSocketInterceptor } from "@mswjs/interceptors/WebSocket";
import { until } from "until-async";
import { XMLHttpRequestInterceptor } from "@mswjs/interceptors/XMLHttpRequest";
import { FetchInterceptor } from "@mswjs/interceptors/fetch";
//#region src/browser/utils/supports.ts
/**
* Checks if the Service Worker API is supproted and available
* in the current browsing context.
*/
function supportsServiceWorker() {
	return typeof navigator !== "undefined" && "serviceWorker" in navigator && typeof location !== "undefined" && location.protocol !== "file:";
}
/**
* Returns a boolean indicating whether the current browser
* supports `ReadableStream` as a `Transferable` when posting
* messages.
*/
function supportsReadableStreamTransfer() {
	try {
		const stream = new ReadableStream({ start: (controller) => controller.close() });
		new MessageChannel().port1.postMessage(stream, [stream]);
		return true;
	} catch {
		return false;
	}
}
//#endregion
//#region src/core/utils/to-response-init.ts
function toResponseInit(response) {
	return {
		status: response.status,
		statusText: response.statusText,
		headers: Object.fromEntries(response.headers.entries())
	};
}
//#endregion
//#region src/browser/utils/get-absolute-worker-url.ts
/**
* Returns an absolute Service Worker URL based on the given
* relative URL (known during the registration).
*/
function getAbsoluteWorkerUrl(workerUrl) {
	return new URL(workerUrl, location.href).href;
}
//#endregion
//#region src/browser/utils/get-worker-by-registration.ts
/**
* Attempts to resolve a Service Worker instance from a given registration,
* regardless of its state (active, installing, waiting).
*/
function getWorkerByRegistration(registration, absoluteWorkerUrl, findWorker) {
	return [
		registration.active,
		registration.installing,
		registration.waiting
	].filter((state) => {
		return state != null;
	}).find((worker) => {
		return findWorker(worker.scriptURL, absoluteWorkerUrl);
	}) || null;
}
//#endregion
//#region src/browser/utils/get-worker-instance.ts
/**
* Returns an active Service Worker instance.
* When not found, registers a new Service Worker.
*/
const getWorkerInstance = async (url, options = {}, findWorker) => {
	const absoluteWorkerUrl = getAbsoluteWorkerUrl(url);
	const mockRegistrations = await navigator.serviceWorker.getRegistrations().then((registrations) => registrations.filter((registration) => getWorkerByRegistration(registration, absoluteWorkerUrl, findWorker)));
	if (!navigator.serviceWorker.controller && mockRegistrations.length > 0) location.reload();
	const [existingRegistration] = mockRegistrations;
	if (existingRegistration) {
		existingRegistration.update();
		return [getWorkerByRegistration(existingRegistration, absoluteWorkerUrl, findWorker), existingRegistration];
	}
	const [registrationError, registrationResult] = await until(async () => {
		const registration = await navigator.serviceWorker.register(url, options);
		return [getWorkerByRegistration(registration, absoluteWorkerUrl, findWorker), registration];
	});
	if (registrationError) {
		if (registrationError.message.includes("(404)")) {
			const scopeUrl = new URL(options?.scope || "/", location.href);
			throw new Error(devUtils.formatMessage(`\
Failed to register a Service Worker for scope ('${scopeUrl.href}') with script ('${absoluteWorkerUrl}'): Service Worker script does not exist at the given path.

Did you forget to run "npx msw init <PUBLIC_DIR>"?

Learn more about creating the Service Worker script: https://mswjs.io/docs/cli/init`));
		}
		throw new Error(devUtils.formatMessage("Failed to register the Service Worker:\n\n%s", registrationError.message));
	}
	return registrationResult;
};
//#endregion
//#region src/browser/utils/worker-channel.ts
const SUPPORTS_SERVICE_WORKER = supportsServiceWorker();
var WorkerEvent = class extends TypedEvent {
	#workerEvent;
	constructor(workerEvent) {
		const type = workerEvent.data.type;
		const data = workerEvent.data.payload;
		/**
		* @note This is the only place we're mapping { type, payload }
		* message structure of the worker. The client references the
		* payload via `event.data`.
		*/
		super(type, { data });
		this.#workerEvent = workerEvent;
	}
	get ports() {
		return this.#workerEvent.ports;
	}
	/**
	* Reply directly to this event using its `MessagePort`.
	*/
	postMessage(type, ...rest) {
		this.#workerEvent.ports[0].postMessage({
			type,
			data: rest[0]
		}, { transfer: rest[1] });
	}
};
var WorkerChannel = class extends Emitter {
	#getWorker;
	#controller;
	constructor(options) {
		super();
		invariant(SUPPORTS_SERVICE_WORKER, "Failed to open a WorkerChannel: Service Worker is not supported in this environment.");
		this.#getWorker = options.getWorker;
		this.#controller = new AbortController();
		navigator.serviceWorker.addEventListener("message", async (event) => {
			const worker = await this.#getWorker();
			if (event.source != null && event.source !== worker) return;
			if (event.data && isObject(event.data) && "type" in event.data) this.emit(new WorkerEvent(event));
		}, { signal: this.#controller.signal });
	}
	/**
	* Send data to the Service Worker controlling this client.
	* This triggers the `message` event listener on ServiceWorkerGlobalScope.
	*/
	postMessage(type) {
		invariant(SUPPORTS_SERVICE_WORKER, "Failed to post message on a WorkerChannel: the Service Worker API is unavailable in this environment. This is likely an issue with MSW. Please report it on GitHub: https://github.com/mswjs/msw/issues");
		this.#getWorker().then((worker) => {
			worker.postMessage(type);
		});
	}
	/**
	* Terminal teardown. Removes the `navigator.serviceWorker` message listener
	* and all emitter subscriptions. The channel is not usable afterwards.
	*/
	terminate() {
		this.#controller.abort();
		this.removeAllListeners();
	}
};
//#endregion
//#region src/browser/utils/deserialize-request.ts
/**
* Converts a given request received from the Service Worker
* into a Fetch `Request` instance.
*/
function deserializeRequest(serializedRequest) {
	return new FetchRequest(serializedRequest.url, { ...serializedRequest });
}
//#endregion
//#region src/browser/utils/validate-worker-scope.ts
/**
* Print a warning if the given Service Worker registration has a scope
* outside of the current page's location. That is to help with debugging
* issues caused by the incorrectly registered Service Worker.
*/
function validateWorkerScope(registration) {
	if (!location.href.startsWith(registration.scope)) devUtils.warn(`Cannot intercept requests on this page because it's outside of the worker's scope ("${registration.scope}"). If you wish to mock API requests on this page, you must resolve this scope issue.

- (Recommended) Register the worker at the root level ("/") of your application.
- Set the "Service-Worker-Allowed" response header to allow out-of-scope workers.`);
}
//#endregion
//#region src/browser/utils/should-invalidate-worker.ts
function shouldInvalidateWorker(prevOptions, nextOptions) {
	return prevOptions.findWorker !== nextOptions.findWorker || prevOptions.serviceWorker.url !== nextOptions.serviceWorker.url || JSON.stringify(prevOptions.serviceWorker.options) !== JSON.stringify(nextOptions.serviceWorker.options);
}
//#endregion
//#region src/browser/sources/service-worker-source.ts
var ServiceWorkerSource = class ServiceWorkerSource extends NetworkSource {
	static #current;
	/**
	* Create a new Service Worker source or reuse an existing one.
	* These sources act as a singleton and only get recreated if the options change.
	*/
	static async from(options) {
		if (ServiceWorkerSource.#current == null) ServiceWorkerSource.#current = new ServiceWorkerSource(options);
		else if (shouldInvalidateWorker(ServiceWorkerSource.#current.#options, options)) {
			await ServiceWorkerSource.#current.terminate();
			ServiceWorkerSource.#current = new ServiceWorkerSource(options);
		}
		return ServiceWorkerSource.#current;
	}
	#options;
	/**
	* @note We cannot use `WeakMap` here as request/response
	* identity cannot be preserved through the client-worker channel.
	*/
	#frames;
	#channel;
	#listenerController;
	#clientPromise;
	#keepAliveInterval;
	workerPromise;
	#workerResolvers;
	#workerState;
	constructor(options) {
		super();
		invariant(supportsServiceWorker(), "Failed to use Service Worker as the network source: the Service Worker API is not supported in this environment");
		this.#options = options;
		this.#frames = /* @__PURE__ */ new Map();
		this.#workerResolvers = Promise.withResolvers();
		this.workerPromise = this.#workerResolvers.promise;
		this.#workerState = "pending";
		this.#channel = new WorkerChannel({ getWorker: () => this.workerPromise.then(([worker]) => worker) });
	}
	async enable() {
		this.#channel.removeAllListeners();
		this.#frames.clear();
		this.#listenerController = new AbortController();
		const [worker, registration] = await this.#startWorker();
		if (worker.state !== "activated") {
			const controller = new AbortController();
			const activationPromise = Promise.withResolvers();
			activationPromise.promise.then(() => controller.abort());
			worker.addEventListener("statechange", () => {
				if (worker.state === "activated") activationPromise.resolve();
			}, { signal: controller.signal });
			await activationPromise.promise;
		}
		this.#channel.postMessage("MOCK_ACTIVATE");
		const clientConfirmationPromise = Promise.withResolvers();
		this.#clientPromise = clientConfirmationPromise.promise;
		this.#channel.once("MOCKING_ENABLED", (event) => {
			clientConfirmationPromise.resolve(event.data.client);
		});
		await clientConfirmationPromise.promise;
		if (!this.#options.quiet) this.#printStartMessage();
		return registration;
	}
	async disable() {
		/**
		* @note Do NOT call `super.disable()` because it removes any "frame" listeners
		* from this network source, effectively turning it off. The Service Worker source
		* is a bit special since it might process in-flight requests that have been performed
		* after it's been disabled.
		*/
		this.#listenerController?.abort();
		this.#listenerController = void 0;
		const closedPromise = Promise.withResolvers();
		this.#channel.once("CLIENT_CLOSED", () => closedPromise.resolve());
		this.#channel.postMessage("CLIENT_CLOSE");
		await closedPromise.promise;
		/**
		* @note Do NOT reset `workerPromise` here. The channel must continue to
		* resolve the currently registered SW so that any in-flight requests the
		* worker forwards after `stop()` can be answered with `PASSTHROUGH` by
		* `#handleRequest`. `#startWorker` swaps in a fresh deferred on re-enable.
		*/
		if (!this.#options.quiet) this.#printStopMessage();
	}
	/**
	* Terminal teardown. Unregisters the Service Worker, tears down the channel,
	* and clears timers. Called when the singleton is being replaced with one
	* that has different options. The instance is not usable afterwards.
	*/
	async terminate() {
		if (this.#keepAliveInterval != null) {
			clearInterval(this.#keepAliveInterval);
			this.#keepAliveInterval = void 0;
		}
		this.#frames.clear();
		this.#channel.terminate();
		this.#listenerController?.abort();
		this.#listenerController = void 0;
		if (this.#workerState === "fulfilled") {
			const [, registration] = await this.workerPromise;
			await registration.unregister();
		}
		if (ServiceWorkerSource.#current === this) ServiceWorkerSource.#current = void 0;
	}
	async #startWorker() {
		if (this.#keepAliveInterval) clearInterval(this.#keepAliveInterval);
		const workerUrl = this.#options.serviceWorker.url;
		const [worker, registration] = await getWorkerInstance(workerUrl, this.#options.serviceWorker.options, this.#options.findWorker || this.#defaultFindWorker);
		if (worker == null) {
			const missingWorkerMessage = this.#options?.findWorker ? devUtils.formatMessage(`Failed to locate the Service Worker registration using a custom "findWorker" predicate.

Please ensure that the custom predicate properly locates the Service Worker registration at "%s".
More details: https://mswjs.io/docs/api/setup-worker/start#findworker
     `, workerUrl) : devUtils.formatMessage(`Failed to locate the Service Worker registration.

This most likely means that the worker script URL "%s" cannot resolve against the actual public hostname (%s). This may happen if your application runs behind a proxy, or has a dynamic hostname.

Please consider using a custom "serviceWorker.url" option to point to the actual worker script location, or a custom "findWorker" option to resolve the Service Worker registration manually. More details: https://mswjs.io/docs/api/setup-worker/start`, workerUrl, location.host);
			throw new Error(missingWorkerMessage);
		}
		if (this.#workerState === "pending") {
			this.#workerResolvers.resolve([worker, registration]);
			this.#workerState = "fulfilled";
		} else {
			/**
			* @note Re-enable after `stop()`: the previous `workerPromise` is already
			* fulfilled and cannot be resolved again. Swap in a pre-resolved one so
			* `getWorker()` sees the new worker instance immediately.
			*/
			this.#workerResolvers = Promise.withResolvers();
			this.#workerResolvers.resolve([worker, registration]);
			this.workerPromise = this.#workerResolvers.promise;
		}
		this.#channel.on("REQUEST", this.#handleRequest.bind(this));
		this.#channel.on("RESPONSE", this.#handleResponse.bind(this));
		this.#channel.on("REQUEST_ERROR", this.#handleRequestError.bind(this));
		window.addEventListener("pagehide", (event) => {
			if (event.persisted) return;
			if (worker.state !== "redundant") this.#channel.postMessage("CLIENT_CLOSE");
			clearInterval(this.#keepAliveInterval);
			window.postMessage({ type: "msw/worker:stop" });
		}, { signal: this.#listenerController?.signal });
		await this.#checkWorkerIntegrity().catch((error) => {
			devUtils.error("Error while checking the worker script integrity. Please report this on GitHub (https://github.com/mswjs/msw/issues) and include the original error below.");
			console.error(error);
		});
		this.#keepAliveInterval = window.setInterval(() => {
			this.#channel.postMessage("KEEPALIVE_REQUEST");
		}, 5e3);
		if (!this.#options.quiet) validateWorkerScope(registration);
		return [worker, registration];
	}
	async #handleRequest(event) {
		const request = deserializeRequest(event.data);
		RequestHandler.cache.set(request, request.clone());
		const frame = new ServiceWorkerHttpNetworkFrame({
			event,
			request
		});
		this.#frames.set(event.data.id, frame);
		await this.queue(frame);
	}
	async #handleResponse(event) {
		const { request, response, isMockedResponse } = event.data;
		const frame = this.#frames.get(request.id);
		/**
		* CORS requests with `mode: "no-cors"` result in "opaque" responses.
		* That kind of responses cannot be manipulated in JavaScript due
		* to the security considerations.
		* @see https://fetch.spec.whatwg.org/#concept-filtered-response-opaque
		* @see https://github.com/mswjs/msw/issues/529
		*/
		if (response.type?.includes("opaque")) {
			this.#frames.delete(request.id);
			frame?.events.removeAllListeners();
			return;
		}
		this.#frames.delete(request.id);
		/**
		* @note A request frame will be missing in case of passthrough after the worker is stopped.
		* Creating a frame is costly so it's better to handle it as an edge case here.
		*/
		if (frame == null) return;
		const fetchRequest = deserializeRequest(request);
		const fetchResponse = response.status === 0 ? Response.error() : new FetchResponse(
			/**
			* Responses may be streams here, but when we create a response object
			* with null-body status codes, like 204, 205, 304 Response will
			* throw when passed a non-null body, so ensure it's null here
			* for those codes
			*/
			FetchResponse.isResponseWithBody(response.status) ? response.body : null,
			{
				...response,
				/**
				* Set response URL if it's not set already.
				* @see https://github.com/mswjs/msw/issues/2030
				* @see https://developer.mozilla.org/en-US/docs/Web/API/Response/url
				*/
				url: request.url
			}
		);
		try {
			frame.events.emit(new ResponseEvent(isMockedResponse ? "response:mocked" : "response:bypass", {
				requestId: frame.data.id,
				request: fetchRequest,
				response: fetchResponse,
				isMockedResponse
			}));
		} finally {
			frame.events.removeAllListeners();
		}
	}
	/**
	* @note A request can settle without ever producing a response
	* (e.g. a passthrough request failing with a network error).
	* The worker never sends the "RESPONSE" message for such requests,
	* so the frame must be released here to prevent it from being retained.
	* No "response:*" event is emitted, consistent with the Node.js source.
	* @see https://github.com/mswjs/msw/issues/2792
	*/
	#handleRequestError(event) {
		const { request } = event.data;
		const frame = this.#frames.get(request.id);
		this.#frames.delete(request.id);
		frame?.events.removeAllListeners();
	}
	#defaultFindWorker = (workerUrl, mockServiceWorkerUrl) => {
		return workerUrl === mockServiceWorkerUrl;
	};
	async #checkWorkerIntegrity() {
		const integrityCheckPromise = Promise.withResolvers();
		this.#channel.postMessage("INTEGRITY_CHECK_REQUEST");
		this.#channel.once("INTEGRITY_CHECK_RESPONSE", (event) => {
			const { checksum, packageVersion } = event.data;
			if (checksum !== "5cd5cf8b54c3a90f82960cedcd637772") devUtils.warn(`The currently registered Service Worker has been generated by a different version of MSW (${packageVersion}) and may not be fully compatible with the installed version.

It's recommended you update your worker script by running this command:

  \u2022 npx msw init <PUBLIC_DIR>

You can also automate this process and make the worker script update automatically upon the library installations. Read more: https://mswjs.io/docs/cli/init.`);
			integrityCheckPromise.resolve();
		});
		return integrityCheckPromise.promise;
	}
	async #printStartMessage() {
		if (this.#workerState === "rejected") return;
		invariant(this.#clientPromise != null, "[ServiceWorkerSource] Failed to print a start message: client confirmation not received");
		const client = await this.#clientPromise;
		const [worker, registration] = await this.workerPromise;
		console.groupCollapsed(`%c${devUtils.formatMessage("Mocking enabled.")}`, "color:orangered;font-weight:bold;");
		console.log("%cDocumentation: %chttps://mswjs.io/docs", "font-weight:bold", "font-weight:normal");
		console.log("Found an issue? https://github.com/mswjs/msw/issues");
		console.log("Worker script URL:", worker.scriptURL);
		console.log("Worker scope:", registration.scope);
		if (client) console.log("Client ID: %s (%s)", client.id, client.frameType);
		console.groupEnd();
	}
	#printStopMessage() {
		console.log(`%c${devUtils.formatMessage("Mocking disabled.")}`, "color:orangered;font-weight:bold;");
	}
};
var ServiceWorkerHttpNetworkFrame = class extends HttpNetworkFrame {
	#event;
	constructor(options) {
		super({ request: options.request });
		this.#event = options.event;
	}
	passthrough() {
		this.#event.postMessage("PASSTHROUGH", { request: { headers: Array.from(this.data.request.headers) } });
	}
	respondWith(response) {
		if (response) this.#respondWith(response);
	}
	errorWith(reason) {
		if (reason instanceof Response) return this.respondWith(reason);
		devUtils.warn(`Uncaught exception in the request handler for "%s %s". This exception has been gracefully handled as a 500 response, however, it's strongly recommended to resolve this error, as it indicates a mistake in your code. If you wish to mock an error response, please see this guide: https://mswjs.io/docs/http/mocking-responses/error-responses`, this.data.request.method, this.data.request.url);
		const error = reason instanceof Error ? reason : new Error(reason?.toString() || "Request failure");
		this.respondWith(HttpResponse.json({
			name: error.name,
			message: error.message,
			stack: error.stack
		}, {
			status: 500,
			statusText: "Request Handler Error"
		}));
	}
	async #respondWith(response) {
		let responseBody;
		let transfer;
		const responseInit = toResponseInit(response);
		if (supportsReadableStreamTransfer()) {
			responseBody = response.body;
			transfer = response.body == null ? void 0 : [response.body];
		} else responseBody = response.body == null ? null : await response.clone().arrayBuffer();
		this.#event.postMessage("MOCK_RESPONSE", {
			...responseInit,
			body: responseBody
		}, transfer);
	}
};
//#endregion
//#region src/browser/sources/fallback-http-source.ts
var FallbackHttpSource = class extends InterceptorSource {
	options;
	constructor(options) {
		super({ interceptors: [new XMLHttpRequestInterceptor(), new FetchInterceptor()] });
		this.options = options;
	}
	enable() {
		super.enable();
		if (!this.options.quiet) this.#printStartMessage();
	}
	disable() {
		super.disable();
		if (!this.options.quiet) this.#printStopMessage();
	}
	#printStartMessage() {
		console.groupCollapsed(`%c${devUtils.formatMessage("Mocking enabled (fallback mode).")}`, "color:orangered;font-weight:bold;");
		console.log("%cDocumentation: %chttps://mswjs.io/docs", "font-weight:bold", "font-weight:normal");
		console.log("Found an issue? https://github.com/mswjs/msw/issues");
		console.groupEnd();
	}
	#printStopMessage() {
		console.log(`%c${devUtils.formatMessage("Mocking disabled.")}`, "color:orangered;font-weight:bold;");
	}
};
//#endregion
//#region src/browser/setup-worker.ts
const DEFAULT_WORKER_URL = "/mockServiceWorker.js";
/**
* Sets up a requests interception in the browser with the given request handlers.
* @param {Array<AnyHandler>} handlers List of request handlers.
*
* @see {@link https://mswjs.io/docs/api/setup-worker `setupWorker()` API reference}
*/
function setupWorker(...handlers) {
	invariant(!isNodeProcess(), devUtils.formatMessage("Failed to execute `setupWorker` in a non-browser environment"));
	const network = defineNetwork({
		sources: [],
		handlers
	});
	return {
		get readyState() {
			return network.readyState;
		},
		async start(options) {
			invariant(network.readyState === 0, devUtils.formatMessage("Failed to call \"worker.start()\": the worker is already started. Remove the redundant \"worker.start()\" call."));
			const httpSource = supportsServiceWorker() ? await ServiceWorkerSource.from({
				serviceWorker: {
					url: options?.serviceWorker?.url?.toString() || DEFAULT_WORKER_URL,
					options: options?.serviceWorker?.options
				},
				findWorker: options?.findWorker,
				quiet: options?.quiet
			}) : new FallbackHttpSource({ quiet: options?.quiet });
			network.configure({
				sources: [httpSource, new InterceptorSource({ interceptors: [new WebSocketInterceptor()] })],
				onUnhandledFrame: options?.onUnhandledFrame ?? "warn",
				context: { quiet: options?.quiet }
			});
			await network.enable();
			if (httpSource instanceof ServiceWorkerSource) {
				const [, registration] = await httpSource.workerPromise;
				return registration;
			}
		},
		async stop() {
			await network.disable();
			window.postMessage({ type: "msw/worker:stop" });
		},
		events: network.events,
		use: network.use.bind(network),
		resetHandlers: network.resetHandlers.bind(network),
		restoreHandlers: network.restoreHandlers.bind(network),
		listHandlers: network.listHandlers.bind(network)
	};
}
//#endregion
//#region src/browser/default-network-options.ts
function createDefaultNetworkOptions(workerUrl = "/mockServiceWorker.js") {
	return {
		sources: [supportsServiceWorker() ? new ServiceWorkerSource({ serviceWorker: { url: workerUrl } }) : new FallbackHttpSource({}), new InterceptorSource({ interceptors: [new WebSocketInterceptor()] })],
		onUnhandledFrame: "warn"
	};
}
const defaultNetworkOptions = createDefaultNetworkOptions();
//#endregion
export { createDefaultNetworkOptions, defaultNetworkOptions, setupWorker };

//# sourceMappingURL=index.js.map