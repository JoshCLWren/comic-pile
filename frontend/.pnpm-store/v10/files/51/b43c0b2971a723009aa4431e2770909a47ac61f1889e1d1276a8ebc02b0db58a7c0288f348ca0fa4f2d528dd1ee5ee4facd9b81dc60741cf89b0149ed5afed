import { n as Interceptor, r as createLogger, t as createRequestId } from "./create-request-id-YobUnJNO.js";
import { c as RequestController, i as isResponseError, n as FetchResponse, s as copyRawHeaders } from "./fetch-utils-C6P6gLLo.js";
import { n as HttpResponseEvent, t as handleRequest } from "./handle-request-y7ajyve5.js";
import { n as patchesRegistry, t as hasConfigurableGlobal } from "./has-configurable-global-Cew-dYqk.js";
import { invariant } from "outvariant";
import { until } from "@open-draft/until";
//#region src/interceptors/fetch/utils/create-network-error.ts
function createNetworkError(cause) {
	return Object.assign(/* @__PURE__ */ new TypeError("Failed to fetch"), { cause });
}
//#endregion
//#region src/interceptors/fetch/utils/follow-redirect.ts
const REQUEST_BODY_HEADERS = [
	"content-encoding",
	"content-language",
	"content-location",
	"content-type",
	"content-length"
];
const kRedirectCount = Symbol("kRedirectCount");
/**
* @see https://github.com/nodejs/undici/blob/a6dac3149c505b58d2e6d068b97f4dc993da55f0/lib/web/fetch/index.js#L1210
*/
async function followFetchRedirect(request, response) {
	if (response.status !== 303 && request.body != null) return Promise.reject(createNetworkError());
	const requestUrl = new URL(request.url);
	let locationUrl;
	try {
		locationUrl = new URL(response.headers.get("location"), request.url);
	} catch (error) {
		return Promise.reject(createNetworkError(error));
	}
	if (!(locationUrl.protocol === "http:" || locationUrl.protocol === "https:")) return Promise.reject(createNetworkError("URL scheme must be a HTTP(S) scheme"));
	if (Reflect.get(request, kRedirectCount) > 20) return Promise.reject(createNetworkError("redirect count exceeded"));
	Object.defineProperty(request, kRedirectCount, { value: (Reflect.get(request, kRedirectCount) || 0) + 1 });
	if (request.mode === "cors" && (locationUrl.username || locationUrl.password) && !sameOrigin(requestUrl, locationUrl)) return Promise.reject(createNetworkError("cross origin not allowed for request mode \"cors\""));
	const requestInit = {};
	if ([301, 302].includes(response.status) && request.method === "POST" || response.status === 303 && !["HEAD", "GET"].includes(request.method)) {
		requestInit.method = "GET";
		requestInit.body = null;
		REQUEST_BODY_HEADERS.forEach((headerName) => {
			request.headers.delete(headerName);
		});
	}
	if (!sameOrigin(requestUrl, locationUrl)) {
		request.headers.delete("authorization");
		request.headers.delete("proxy-authorization");
		request.headers.delete("cookie");
		request.headers.delete("host");
	}
	/**
	* @note Undici "safely" extracts the request body.
	* I suspect we cannot dispatch this request again
	* since its body has been read and the stream is locked.
	*/
	requestInit.headers = request.headers;
	const finalResponse = await fetch(new Request(locationUrl, requestInit));
	Object.defineProperty(finalResponse, "redirected", {
		value: true,
		configurable: true
	});
	return finalResponse;
}
/**
* @see https://github.com/nodejs/undici/blob/a6dac3149c505b58d2e6d068b97f4dc993da55f0/lib/web/fetch/util.js#L761
*/
function sameOrigin(left, right) {
	if (left.origin === right.origin && left.origin === "null") return true;
	if (left.protocol === right.protocol && left.hostname === right.hostname && left.port === right.port) return true;
	return false;
}
//#endregion
//#region src/interceptors/fetch/utils/brotli-decompress.browser.ts
var BrotliDecompressionStream = class extends TransformStream {
	constructor() {
		console.warn("[Interceptors]: Brotli decompression of response streams is not supported in the browser");
		super({ transform(chunk, controller) {
			controller.enqueue(chunk);
		} });
	}
};
//#endregion
//#region src/interceptors/fetch/utils/decompression.ts
var PipelineStream = class extends TransformStream {
	constructor(transformStreams, ...strategies) {
		super({}, ...strategies);
		const readable = [super.readable, ...transformStreams].reduce((readable, transform) => readable.pipeThrough(transform));
		Object.defineProperty(this, "readable", { get() {
			return readable;
		} });
	}
};
function parseContentEncoding(contentEncoding) {
	return contentEncoding.toLowerCase().split(",").map((coding) => coding.trim());
}
function createDecompressionStream(contentEncoding) {
	return new PipelineStream(parseContentEncoding(contentEncoding).reduceRight((transformers, coding) => {
		if (coding === "gzip" || coding === "x-gzip") return transformers.concat(new DecompressionStream("gzip"));
		else if (coding === "deflate") return transformers.concat(new DecompressionStream("deflate"));
		else if (coding === "br") return transformers.concat(new BrotliDecompressionStream());
		else transformers.length = 0;
		return transformers;
	}, []));
}
/**
* Returns a boolean indicating whether the given response
* has a body encoded with a non-empty "content-encoding".
*/
function isCompressedResponse(response) {
	if (response.body === null) return false;
	const contentEncoding = response.headers.get("content-encoding");
	return contentEncoding !== null && contentEncoding.trim() !== "";
}
/**
* Decompresses the body of the given compressed response.
*/
function decompressResponse(response) {
	invariant(isCompressedResponse(response), "Failed to decompress a response: expected a response with a body and a non-empty \"content-encoding\" header");
	const decompressionStream = createDecompressionStream(response.headers.get("content-encoding"));
	response.body.pipeTo(decompressionStream.writable);
	return decompressionStream.readable;
}
//#endregion
//#region src/utils/clone-response.ts
/** Clone for observers without letting their unread body block caller cancellation. */
function cloneResponse(response) {
	const clone = FetchResponse.clone(response);
	if (!response.body || !clone.body) return [response, clone];
	const observer = wrapResponse(clone);
	return [wrapResponse(response, observer.cancel).response, observer.response];
}
function wrapResponse(response, onCancel) {
	const body = response.body;
	const reader = body.getReader();
	const cancel = (reason) => {
		return body.locked ? reader.cancel(reason) : body.cancel(reason);
	};
	const stream = new ReadableStream({
		async pull(controller) {
			try {
				const { done, value } = await reader.read();
				if (done) {
					controller.close();
					reader.releaseLock();
					return;
				}
				controller.enqueue(value);
			} catch (error) {
				controller.error(error);
				reader.releaseLock();
			}
		},
		async cancel(reason) {
			try {
				const cancellation = cancel(reason);
				if (onCancel) await Promise.all([cancellation, onCancel(reason)]);
				else cancellation.catch(() => {});
			} finally {
				reader.releaseLock();
			}
		}
	}, { highWaterMark: 0 });
	const wrappedResponse = new FetchResponse(stream, response);
	copyRawHeaders(response.headers, wrappedResponse.headers);
	Object.defineProperties(wrappedResponse, {
		type: { value: response.type },
		redirected: { value: response.redirected }
	});
	return {
		response: wrappedResponse,
		cancel
	};
}
//#endregion
//#region src/interceptors/fetch/web.ts
const logger = createLogger("fetch");
/**
* Intercept `fetch` requests in the browser.
*/
var FetchInterceptor = class extends Interceptor {
	static {
		this.symbol = Symbol.for("fetch-interceptor");
	}
	predicate() {
		return hasConfigurableGlobal("fetch");
	}
	async setup() {
		logger.verbose("patching global fetch...");
		this.subscriptions.push(patchesRegistry.applyPatch(globalThis, "fetch", (realFetch) => {
			return async (input, init) => {
				const requestId = createRequestId();
				/**
				* @note Resolve potentially relative request URL
				* against the present `location`. This is mainly
				* for native `fetch` in JSDOM.
				* @see https://github.com/mswjs/msw/issues/1625
				*/
				const resolvedInput = typeof input === "string" && typeof location !== "undefined" && !URL.canParse(input) ? new URL(input, location.href) : input;
				const request = new Request(resolvedInput, init);
				const responsePromise = Promise.withResolvers();
				const controller = new RequestController(request, {
					passthrough: async () => {
						logger.verbose("performing request as-is");
						/**
						* @note Perform a clone of the request instance, not the instance itself.
						* Performing a request consumes its body, and the "response" listener
						* must still be able to read it. The clone is created right before
						* the request is performed, so it preserves any modifications made
						* to the intercepted request in the "request" listener.
						*
						* This also keeps the request instance emitted on the "response" event
						* referentially equal to the one emitted on the "request" event
						* so the consumer can associate the two by identity.
						*/
						const requestClone = request.clone();
						const [responseError, originalResponse] = await until(() => realFetch(requestClone));
						if (responseError) return responsePromise.reject(responseError);
						logger.verbose("original fetch performed %o", originalResponse);
						if (this.emitter.listenerCount("response") > 0) {
							logger.verbose("emitting the \"response\" event");
							const [response, responseClone] = cloneResponse(originalResponse);
							await this.emitter.emitAsPromise(new HttpResponseEvent({
								initiator: request,
								request,
								requestId,
								response: responseClone,
								responseType: "original"
							}));
							responsePromise.resolve(response);
							return;
						}
						responsePromise.resolve(originalResponse);
					},
					respondWith: async (rawResponse) => {
						if (isResponseError(rawResponse)) {
							logger.verbose("request errored %o", { response: rawResponse });
							responsePromise.reject(createNetworkError(rawResponse));
							return;
						}
						/**
						* @note Forward the mocked response instance as-is. Wrapping it
						* in a new `Response` drops any runtime-specific state the
						* environment attached to it (e.g. the `webSocket` property
						* of a "101 Switching Protocols" response in workerd).
						* A plain `Response` is already guaranteed to be valid by the
						* environment, and a `FetchResponse` manages its own
						* non-configurable state (status, URL) across clones.
						*
						* The only exception is a compressed mocked response body:
						* a body cannot be swapped in place, so it must be a new instance.
						*/
						let response;
						if (isCompressedResponse(rawResponse)) {
							response = new FetchResponse(decompressResponse(rawResponse), {
								status: rawResponse.status,
								statusText: rawResponse.statusText,
								headers: rawResponse.headers
							});
							copyRawHeaders(rawResponse.headers, response.headers);
						} else response = rawResponse;
						FetchResponse.setUrl(request.url, response);
						/**
						* Undici's handling of following redirect responses.
						* Treat the "manual" redirect mode as a regular mocked response.
						* This way, the client can manually follow the redirect it receives.
						* @see https://github.com/nodejs/undici/blob/a6dac3149c505b58d2e6d068b97f4dc993da55f0/lib/web/fetch/index.js#L1173
						*/
						if (FetchResponse.isRedirectResponse(response.status)) {
							if (request.redirect === "error") {
								responsePromise.reject(createNetworkError("unexpected redirect"));
								return;
							}
							if (request.redirect === "follow") {
								followFetchRedirect(request, response).then((response) => {
									responsePromise.resolve(response);
								}, (reason) => {
									responsePromise.reject(reason);
								});
								return;
							}
						}
						if (this.emitter.listenerCount("response") > 0) {
							logger.verbose("emitting the \"response\" event");
							const [callerResponse, responseClone] = cloneResponse(response);
							await this.emitter.emitAsPromise(new HttpResponseEvent({
								initiator: request,
								response: responseClone,
								responseType: "mock",
								request,
								requestId
							}));
							responsePromise.resolve(callerResponse);
							return;
						}
						responsePromise.resolve(response);
					},
					errorWith: (reason) => {
						logger.verbose("request aborted %o", { reason });
						responsePromise.reject(reason);
					}
				}, {
					logger,
					requestId
				});
				logger.verbose("awaiting request resolution");
				logger.verbose("emitting the \"request\" event for %s listener(s)...", this.emitter.listenerCount("request"));
				/**
				* @note Give the consumer a chance to abort the request before
				* it is dispatched. Fetch queues the request processing as a
				* task, so a signal aborted synchronously after `fetch()` must
				* prevent the request from ever reaching the "request" listeners.
				* Without this, the first listener is invoked synchronously
				* within the `fetch()` call itself.
				*/
				await Promise.resolve();
				await handleRequest({
					initiator: request,
					request,
					requestId,
					emitter: this.emitter,
					controller,
					logger
				});
				return responsePromise.promise;
			};
		}));
		logger.verbose("global fetch patched: %s", globalThis.fetch.name);
	}
};
//#endregion
export { FetchInterceptor as t };

//# sourceMappingURL=web-CCLERSZF.js.map