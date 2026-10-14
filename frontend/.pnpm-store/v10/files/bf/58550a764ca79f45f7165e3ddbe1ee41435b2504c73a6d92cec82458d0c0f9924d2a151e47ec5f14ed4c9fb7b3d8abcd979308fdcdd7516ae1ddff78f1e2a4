import { _ as Handler, d as getRawSetCookie, g as getCallFrame, h as devUtils, l as copyResponseOwnProperties } from "./cookie-store.js";
import { isNodeProcess } from "is-node-process";
import { FetchResponse } from "@mswjs/interceptors";
//#region src/core/utils/internal/is-iterable.ts
/**
* Determines if the given function is an iterator.
*/
function isIterable(fn) {
	if (!fn) return false;
	return Reflect.has(fn, Symbol.iterator) || Reflect.has(fn, Symbol.asyncIterator);
}
//#endregion
//#region src/core/utils/internal/observe-response-body-stream.ts
/**
* Observe the `ReadableStream` body of the given response.
* Returns a copy of that response whose body reports when it has
* settled (was read to completion, errored, or canceled by the consumer).
* Returns `null` for responses whose body cannot be observed
* (no body, already used, or locked).
*/
function observeResponseBodyStream(response) {
	if (response.body == null || response.bodyUsed || response.body.locked) return null;
	const settled = Promise.withResolvers();
	const reader = response.body.getReader();
	/**
	* @note Relay the body through a manual underlying source instead of
	* `.pipeThrough(new TransformStream({ flush, cancel }))`. The `cancel`
	* transformer callback is not implemented in Chromium, which loses
	* the stream error/cancelation signals there entirely.
	*/
	const observedStream = new ReadableStream({
		async pull(controller) {
			try {
				const readResult = await reader.read();
				if (readResult.done) {
					settled.resolve();
					controller.close();
					return;
				}
				controller.enqueue(readResult.value);
			} catch (error) {
				settled.resolve();
				throw error;
			}
		},
		async cancel(reason) {
			settled.resolve();
			await reader.cancel(reason);
		}
	});
	/**
	* @note Reconstruct the response because the body of an existing
	* response cannot be replaced. Use `FetchResponse` to support
	* non-standard response status codes (e.g. 101).
	*/
	const observedResponse = new FetchResponse(observedStream, {
		status: response.status,
		statusText: response.statusText,
		headers: response.headers
	});
	copyResponseOwnProperties(response, observedResponse);
	return {
		response: observedResponse,
		settled: settled.promise
	};
}
//#endregion
//#region src/core/handlers/request-handler.ts
var RequestHandler = class RequestHandler extends Handler {
	static cache = /* @__PURE__ */ new WeakMap();
	kind = "request";
	resolver;
	resolverIterator;
	resolverIteratorResult;
	resolverIteratorCleanups;
	options;
	scheduledCleanups;
	info;
	/**
	* Indicates whether this request handler has been used
	* (its resolver has successfully executed).
	*/
	isUsed;
	constructor(args) {
		super();
		this.resolver = args.resolver;
		this.options = args.options;
		this.scheduledCleanups = /* @__PURE__ */ new Map();
		const callFrame = getCallFrame(/* @__PURE__ */ new Error());
		this.info = {
			...args.info,
			callFrame
		};
		this.isUsed = false;
	}
	/**
	* Reset the runtime state accumulated during response resolution,
	* such as generator iterator progress. Called when this handler is
	* removed from the active handlers list so re-adding it later starts
	* from a clean state.
	*/
	reset() {
		this.scheduledCleanups.clear();
		const iterator = this.resolverIterator;
		this.resolverIterator = void 0;
		this.resolverIteratorResult = void 0;
		this.resolverIteratorCleanups = void 0;
		if (typeof iterator?.return === "function") Promise.resolve(iterator.return());
	}
	/**
	* Restore this handler so it can match requests again after being
	* exhausted (e.g. via `{ once: true }`). Also clears any accumulated
	* resolution state.
	*/
	restore() {
		if (this.options?.once) {
			this.reset();
			this.isUsed = false;
		}
	}
	/**
	* Parse the intercepted request to extract additional information from it.
	* Parsed result is then exposed to other methods of this request handler.
	*/
	async parse(_args) {
		return {};
	}
	/**
	* Test if this handler matches the given request.
	*
	* This method is not used internally but is exposed
	* as a convenience method for consumers writing custom
	* handlers.
	*/
	async test(args) {
		const parsedResult = await this.parse({
			request: args.request,
			resolutionContext: args.resolutionContext
		});
		return this.predicate({
			request: args.request,
			parsedResult,
			resolutionContext: args.resolutionContext
		});
	}
	extendResolverArgs(_args) {
		return {};
	}
	cloneRequestOrGetFromCache(request) {
		const existingClone = RequestHandler.cache.get(request);
		if (typeof existingClone !== "undefined") return existingClone;
		const clonedRequest = request.clone();
		RequestHandler.cache.set(request, clonedRequest);
		return clonedRequest;
	}
	/**
	* Execute this request handler and produce a mocked response
	* using the given resolver function.
	*/
	async run(args) {
		if (this.isUsed && this.options?.once) return null;
		const requestClone = this.cloneRequestOrGetFromCache(args.request);
		const parsedResult = await this.parse({
			request: args.request,
			resolutionContext: args.resolutionContext
		});
		if (!await this.predicate({
			request: args.request,
			parsedResult,
			resolutionContext: args.resolutionContext
		})) return null;
		if (this.isUsed && this.options?.once) return null;
		this.isUsed = true;
		const executeResolver = this.wrapResolver(this.resolver);
		const resolverExtras = this.extendResolverArgs({
			request: args.request,
			parsedResult
		});
		const listenerController = new AbortController();
		/**
		* @note Initialize the `finalize` machinery lazily, on the first
		* access of the `finalize` property by the resolver. If the resolver
		* never accesses it, the handler behaves as if `finalize` never
		* existed: no abort listeners, no scheduled cleanups, and no response
		* body stream observation (see `this.complete()`).
		*/
		let finalizeFunction;
		const getFinalize = () => {
			if (finalizeFunction == null) {
				if (!args.request.signal.aborted) args.request.signal.addEventListener("abort", () => this.runScheduledCleanups(args.requestId), {
					once: true,
					signal: listenerController.signal
				});
				finalizeFunction = (callback) => {
					this.scheduleCleanup(args.requestId, callback);
					/**
					* @note Run the cleanup immediately if the request has already
					* been aborted. The "abort" listener above never fires for an
					* already-aborted signal (and fires at most once), while
					* long-lived resolvers (streams, generators) may never settle
					* to run the cleanups on completion.
					*/
					if (args.request.signal.aborted) this.runScheduledCleanups(args.requestId);
				};
			}
			return finalizeFunction;
		};
		const mockedResponse = await executeResolver({
			...resolverExtras,
			get finalize() {
				return getFinalize();
			},
			requestId: args.requestId,
			request: args.request
		}).catch((errorOrResponse) => {
			if (errorOrResponse instanceof Response) return errorOrResponse;
			throw errorOrResponse;
		}).finally(() => {
			listenerController.abort();
		});
		if (mockedResponse) forwardResponseCookies(mockedResponse);
		return this.createExecutionResult({
			request: requestClone,
			requestId: args.requestId,
			response: mockedResponse,
			parsedResult
		});
	}
	wrapResolver(resolver) {
		return async (info) => {
			if (!this.resolverIterator) {
				let result;
				try {
					result = await resolver(info);
				} catch (error) {
					await this.runScheduledCleanups(info.requestId);
					throw error;
				}
				if (!isIterable(result)) return this.complete({
					request: info.request,
					requestId: info.requestId,
					response: result
				});
				/**
				* @note Carry over any previously registered cleanups onto the iterator cleanups.
				* This is only relevant if "finalize()" is called in a regular resolver that
				* returns an iterator.
				* @example
				* http.get('/', async ({ finalize }) => {
				*   finalize(cleanup)
				*   return (async function*() {})()
				* })
				*/
				const existingCleanups = this.scheduledCleanups.get(info.requestId);
				if (existingCleanups != null && existingCleanups.length > 0) {
					this.resolverIteratorCleanups = existingCleanups;
					this.scheduledCleanups.delete(info.requestId);
				}
				this.resolverIterator = Symbol.iterator in result ? result[Symbol.iterator]() : result[Symbol.asyncIterator]();
			}
			this.isUsed = false;
			const { done, value } = await this.resolverIterator.next();
			const nextResponse = await value;
			if (nextResponse) this.resolverIteratorResult = nextResponse.clone();
			if (done) {
				this.isUsed = true;
				return this.complete({
					request: info.request,
					requestId: info.requestId,
					response: this.resolverIteratorResult?.clone()
				});
			}
			return nextResponse;
		};
	}
	createExecutionResult(args) {
		return {
			handler: this,
			request: args.request,
			requestId: args.requestId,
			response: args.response,
			parsedResult: args.parsedResult
		};
	}
	scheduleCleanup(requestId, callback) {
		if (this.resolverIterator) {
			(this.resolverIteratorCleanups ||= []).unshift(callback);
			return;
		}
		const cleanups = this.scheduledCleanups.get(requestId) || [];
		cleanups.unshift(callback);
		this.scheduledCleanups.set(requestId, cleanups);
	}
	async exhaustCleanups(cleanups) {
		const errors = [];
		for (const cleanup of cleanups) try {
			await cleanup();
		} catch (error) {
			if (error instanceof Error) errors.push(error);
		}
		if (errors.length > 0) devUtils.error("Failed to execute cleanup for request handler \"%s\"", this.info.header, new AggregateError(errors, `Failed to execute cleanup for request handler "${this.info.header}"`));
	}
	/**
	* Remove and return the cleanups scheduled for the given request
	* (or the pending iterator cleanups for generator resolvers).
	*/
	takeScheduledCleanups(requestId) {
		if (this.resolverIterator && this.resolverIteratorCleanups != null && this.resolverIteratorCleanups.length > 0) {
			const cleanups = this.resolverIteratorCleanups;
			this.resolverIteratorCleanups = void 0;
			return cleanups;
		}
		const cleanups = this.scheduledCleanups.get(requestId);
		if (!cleanups || cleanups.length === 0) return;
		this.scheduledCleanups.delete(requestId);
		return cleanups;
	}
	async runScheduledCleanups(requestId) {
		const cleanups = this.takeScheduledCleanups(requestId);
		if (cleanups) await this.exhaustCleanups(cleanups);
	}
	/**
	* Conclude the response resolution for the given request.
	* Runs the scheduled cleanups immediately for responses without a
	* `ReadableStream` body. For streamed responses, returns an observed
	* copy of the response and defers the cleanups until its body settles
	* (is read to completion, errored, or canceled) or the request is
	* aborted, whichever comes first.
	*/
	async complete(args) {
		const cleanups = this.takeScheduledCleanups(args.requestId);
		if (!cleanups) return args.response;
		const observedResponse = args.response ? observeResponseBodyStream(args.response) : null;
		if (!observedResponse) {
			await this.exhaustCleanups(cleanups);
			return args.response;
		}
		const listenerController = new AbortController();
		const runCleanupsOnce = () => {
			if (listenerController.signal.aborted) return;
			listenerController.abort();
			this.exhaustCleanups(cleanups);
		};
		observedResponse.settled.then(runCleanupsOnce);
		/**
		* @note Also run the cleanups when the request is aborted.
		* Stream cancellation does not always propagate to the observed
		* response (e.g. if an unconsumed clone of the response exists),
		* while the request abort reliably means the response is unused.
		*/
		if (args.request.signal.aborted) runCleanupsOnce();
		else args.request.signal.addEventListener("abort", runCleanupsOnce, {
			once: true,
			signal: listenerController.signal
		});
		return observedResponse.response;
	}
};
/**
* Forwards the cookies from the given response to `document.cookie`.
*/
function forwardResponseCookies(response) {
	if (isNodeProcess() || typeof document === "undefined") return;
	for (const cookieString of getRawSetCookie(response)) document.cookie = cookieString;
}
//#endregion
export { RequestHandler as t };

//# sourceMappingURL=request-handler.js.map