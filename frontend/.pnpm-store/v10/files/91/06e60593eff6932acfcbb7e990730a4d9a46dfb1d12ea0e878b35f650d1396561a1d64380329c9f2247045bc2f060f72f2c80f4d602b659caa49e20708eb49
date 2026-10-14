var MockServiceWorker = (function(exports) {
	Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
	//#region node_modules/.pnpm/is-node-process@1.2.0/node_modules/is-node-process/lib/index.mjs
	function isNodeProcess() {
		if (typeof navigator !== "undefined" && navigator.product === "ReactNative") return true;
		if (typeof process !== "undefined") {
			const type = process.type;
			if (type === "renderer" || type === "worker") return false;
			return !!(process.versions && process.versions.node);
		}
		return false;
	}
	//#endregion
	//#region src/core/handlers/handler.ts
	/**
	* The base class for all the handlers.
	*/
	var Handler = class {
		/**
		* Reset the runtime state this handler accumulated while handling
		* the network (e.g. generator resolver progress).
		*
		* @note This method is invoked automatically when the handlers are
		* reset (e.g. `server.resetHandlers()`).
		*/
		reset() {}
		/**
		* Restore this handler so it can handle the network again after
		* being exhausted (e.g. via `{ once: true }`).
		*
		* @note This method is invoked automatically when the handlers are
		* restored (e.g. `server.restoreHandlers()`).
		*/
		restore() {}
		/**
		* Release the resources held by this handler.
		*
		* @note This method is invoked automatically when the network is
		* disabled (e.g. `server.close()`). Override it in the handlers that
		* hold onto anything beyond a single frame, like timers, connections,
		* or event listeners. Returning a promise makes the network await
		* this handler's disposal before it tears itself down.
		*/
		dispose() {}
	};
	//#endregion
	//#region src/core/utils/internal/get-call-frame.ts
	const SOURCE_FRAME = /[/\\]msw[/\\]src[/\\](.+)/;
	const BUILD_FRAME = /(node_modules)?[/\\]lib[/\\](core|browser|node|iife)[/\\]|^[^/\\]*$/;
	/**
	* Return the stack trace frame of a function's invocation.
	*/
	function getCallFrame(error) {
		const stack = error.stack;
		if (!stack) return;
		const declarationFrame = stack.split("\n").slice(1).find((frame) => {
			return !(SOURCE_FRAME.test(frame) || BUILD_FRAME.test(frame));
		});
		if (!declarationFrame) return;
		return declarationFrame.replace(/\s*at [^()]*\(([^)]+)\)/, "$1").replace(/^@/, "");
	}
	//#endregion
	//#region src/core/utils/internal/is-iterable.ts
	/**
	* Determines if the given function is an iterator.
	*/
	function isIterable(fn) {
		if (!fn) return false;
		return Reflect.has(fn, Symbol.iterator) || Reflect.has(fn, Symbol.asyncIterator);
	}
	//#endregion
	//#region node_modules/.pnpm/outvariant@1.4.3/node_modules/outvariant/lib/index.mjs
	var POSITIONALS_EXP = /(%?)(%([sdijo]))/g;
	function serializePositional(positional, flag) {
		switch (flag) {
			case "s": return positional;
			case "d":
			case "i": return Number(positional);
			case "j": return JSON.stringify(positional);
			case "o": {
				if (typeof positional === "string") return positional;
				const json = JSON.stringify(positional);
				if (json === "{}" || json === "[]" || /^\[object .+?\]$/.test(json)) return positional;
				return json;
			}
		}
	}
	function format(message, ...positionals) {
		if (positionals.length === 0) return message;
		let positionalIndex = 0;
		let formattedMessage = message.replace(POSITIONALS_EXP, (match, isEscaped, _, flag) => {
			const positional = positionals[positionalIndex];
			const value = serializePositional(positional, flag);
			if (!isEscaped) {
				positionalIndex++;
				return value;
			}
			return match;
		});
		if (positionalIndex < positionals.length) formattedMessage += ` ${positionals.slice(positionalIndex).join(" ")}`;
		formattedMessage = formattedMessage.replace(/%{2,2}/g, "%");
		return formattedMessage;
	}
	var STACK_FRAMES_TO_IGNORE = 2;
	function cleanErrorStack(error) {
		if (!error.stack) return;
		const nextStack = error.stack.split("\n");
		nextStack.splice(1, STACK_FRAMES_TO_IGNORE);
		error.stack = nextStack.join("\n");
	}
	var InvariantError = class extends Error {
		constructor(message, ...positionals) {
			super(message);
			this.message = message;
			this.name = "Invariant Violation";
			this.message = format(message, ...positionals);
			cleanErrorStack(this);
		}
	};
	var invariant$1 = (predicate, message, ...positionals) => {
		if (!predicate) throw new InvariantError(message, ...positionals);
	};
	invariant$1.as = (ErrorConstructor, predicate, message, ...positionals) => {
		if (!predicate) {
			const formatMessage = positionals.length === 0 ? message : format(message, ...positionals);
			let error;
			try {
				error = Reflect.construct(ErrorConstructor, [formatMessage]);
			} catch (err) {
				error = ErrorConstructor(formatMessage);
			}
			throw error;
		}
	};
	//#endregion
	//#region src/core/utils/internal/dev-utils.ts
	const LIBRARY_PREFIX = "[MSW]";
	/**
	* Formats a given message by appending the library's prefix string.
	*/
	function formatMessage(message, ...positionals) {
		const interpolatedMessage = format(message, ...positionals);
		return `${LIBRARY_PREFIX} ${interpolatedMessage}`;
	}
	/**
	* Prints a library-specific warning.
	*/
	function warn(message, ...positionals) {
		console.warn(formatMessage(message, ...positionals));
	}
	/**
	* Prints a library-specific error.
	*/
	function error(message, ...positionals) {
		console.error(formatMessage(message, ...positionals));
	}
	const devUtils = {
		formatMessage,
		warn,
		error
	};
	/**
	* Internal error instance.
	* Used to differentiate the library errors that must be forwarded
	* to the user from the unhandled exceptions. Use this if you don't
	* wish for the error to be coerced to a 500 fallback response.
	*/
	var InternalError = class extends Error {
		constructor(message) {
			super(message);
			this.name = "InternalError";
		}
	};
	//#endregion
	//#region src/core/utils/http-status-messages.ts
	/**
	* Reason phrases of the known HTTP status codes.
	* @see https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml
	*/
	const httpStatusMessages = {
		100: "Continue",
		101: "Switching Protocols",
		102: "Processing",
		103: "Early Hints",
		200: "OK",
		201: "Created",
		202: "Accepted",
		203: "Non-Authoritative Information",
		204: "No Content",
		205: "Reset Content",
		206: "Partial Content",
		207: "Multi-Status",
		208: "Already Reported",
		226: "IM Used",
		300: "Multiple Choices",
		301: "Moved Permanently",
		302: "Found",
		303: "See Other",
		304: "Not Modified",
		305: "Use Proxy",
		307: "Temporary Redirect",
		308: "Permanent Redirect",
		400: "Bad Request",
		401: "Unauthorized",
		402: "Payment Required",
		403: "Forbidden",
		404: "Not Found",
		405: "Method Not Allowed",
		406: "Not Acceptable",
		407: "Proxy Authentication Required",
		408: "Request Timeout",
		409: "Conflict",
		410: "Gone",
		411: "Length Required",
		412: "Precondition Failed",
		413: "Payload Too Large",
		414: "URI Too Long",
		415: "Unsupported Media Type",
		416: "Range Not Satisfiable",
		417: "Expectation Failed",
		418: "I'm a Teapot",
		421: "Misdirected Request",
		422: "Unprocessable Entity",
		423: "Locked",
		424: "Failed Dependency",
		425: "Too Early",
		426: "Upgrade Required",
		428: "Precondition Required",
		429: "Too Many Requests",
		431: "Request Header Fields Too Large",
		451: "Unavailable For Legal Reasons",
		500: "Internal Server Error",
		501: "Not Implemented",
		502: "Bad Gateway",
		503: "Service Unavailable",
		504: "Gateway Timeout",
		505: "HTTP Version Not Supported",
		506: "Variant Also Negotiates",
		507: "Insufficient Storage",
		508: "Loop Detected",
		509: "Bandwidth Limit Exceeded",
		510: "Not Extended",
		511: "Network Authentication Required"
	};
	//#endregion
	//#region src/core/utils/response-decorators.ts
	const kSetCookie = Symbol("kSetCookie");
	function normalizeResponseInit(init = {}) {
		const status = init?.status || 200;
		const statusText = init?.statusText || httpStatusMessages[status] || "";
		const headers = new Headers(init?.headers);
		return {
			...init,
			headers,
			status,
			statusText
		};
	}
	function decorateResponse(response, init) {
		if (init.type) Object.defineProperty(response, "type", {
			value: init.type,
			enumerable: true,
			writable: false
		});
		const responseCookies = init.headers.getSetCookie();
		if (responseCookies) Object.defineProperty(response, kSetCookie, {
			value: responseCookies,
			enumerable: false,
			writable: false
		});
		return response;
	}
	function getRawSetCookie(response) {
		return Reflect.get(response, kSetCookie) || [];
	}
	/**
	* Copy the given response own properties, like internal symbols,
	* onto another response. Used for faithful internal copying of responses.
	*/
	function copyResponseOwnProperties(source, target) {
		for (const propertyName of Reflect.ownKeys(source)) {
			const descriptor = Object.getOwnPropertyDescriptor(source, propertyName);
			const existingDescriptor = Object.getOwnPropertyDescriptor(target, propertyName);
			if (descriptor && existingDescriptor == null) Object.defineProperty(target, propertyName, descriptor);
		}
	}
	//#endregion
	//#region node_modules/.pnpm/rettime@0.11.12/node_modules/rettime/build/lens-list.mjs
	var LensList = class {
		#list;
		#lens;
		constructor() {
			this.#list = [];
			this.#lens = /* @__PURE__ */ new Map();
		}
		get [Symbol.iterator]() {
			return this.#list[Symbol.iterator].bind(this.#list);
		}
		entries() {
			return this.#lens.entries();
		}
		/**
		* Return an order-sensitive list of values by the given key.
		*/
		get(key) {
			return this.#lens.get(key) || [];
		}
		/**
		* Return an order-sensitive list of all values.
		*/
		getAll() {
			return this.#list.map(([, value]) => value);
		}
		/**
		* Append a new value to the given key.
		*/
		append(key, value) {
			this.#list.push([key, value]);
			this.#openLens(key, (list) => list.push(value));
		}
		/**
		* Prepend a new value to the given key.
		*/
		prepend(key, value) {
			this.#list.unshift([key, value]);
			this.#openLens(key, (list) => list.unshift(value));
		}
		/**
		* Delete the value belonging to the given key.
		* Returns `true` if the value was present and removed, `false` otherwise.
		*/
		delete(key, value) {
			if (this.size === 0) return false;
			const values = this.#lens.get(key);
			if (!values) return false;
			const index = values.indexOf(value);
			if (index === -1) return false;
			values.splice(index, 1);
			this.#list.splice(this.#list.findIndex((item) => item[0] === key && item[1] === value), 1);
			return true;
		}
		/**
		* Delete all values belogning to the given key.
		*/
		deleteAll(key) {
			if (this.size === 0) return;
			this.#list = this.#list.filter((item) => item[0] !== key);
			this.#lens.delete(key);
		}
		get size() {
			return this.#list.length;
		}
		clear() {
			if (this.size === 0) return;
			this.#list.length = 0;
			this.#lens.clear();
		}
		#openLens(key, setter) {
			setter(this.#lens.get(key) || this.#lens.set(key, []).get(key));
		}
	};
	//#endregion
	//#region node_modules/.pnpm/rettime@0.11.12/node_modules/rettime/build/index.mjs
	const kDefaultPrevented$1 = Symbol("kDefaultPrevented");
	const kPropagationStopped = Symbol("kPropagationStopped");
	const kImmediatePropagationStopped = Symbol("kImmediatePropagationStopped");
	var TypedEvent = class extends MessageEvent {
		/**
		* @note Keep a placeholder property with the return type
		* because the type must be set somewhere in order to be
		* correctly associated and inferred from the event.
		*/
		#returnType;
		[kDefaultPrevented$1];
		[kPropagationStopped];
		[kImmediatePropagationStopped];
		constructor(...args) {
			/**
			* @note Always provide an event initializer. Some runtimes
			* (e.g. Cloudflare Workers) throw when constructing a `MessageEvent`
			* with an `undefined` initializer, unlike Node.js and browsers.
			*/
			super(args[0], args[1] ?? {});
			this[kDefaultPrevented$1] = false;
		}
		get defaultPrevented() {
			return this[kDefaultPrevented$1];
		}
		preventDefault() {
			super.preventDefault();
			this[kDefaultPrevented$1] = true;
		}
		stopImmediatePropagation() {
			/**
			* @note Despite `.stopPropagation()` and `.stopImmediatePropagation()` being defined
			* in Node.js, they do nothing. It is safe to re-define them.
			*/
			super.stopImmediatePropagation();
			this[kImmediatePropagationStopped] = true;
		}
	};
	var Emitter = class {
		#listeners;
		#listenerOptions;
		#listenerAbortCleanups;
		#typelessListeners;
		#hookListeners;
		#hookListenerOptions;
		#hookListenerAbortCleanups;
		hooks;
		constructor() {
			this.#listeners = new LensList();
			this.#listenerOptions = /* @__PURE__ */ new WeakMap();
			this.#listenerAbortCleanups = /* @__PURE__ */ new WeakMap();
			this.#typelessListeners = /* @__PURE__ */ new WeakSet();
			this.#hookListeners = new LensList();
			this.#hookListenerOptions = /* @__PURE__ */ new WeakMap();
			this.#hookListenerAbortCleanups = /* @__PURE__ */ new WeakMap();
			this.hooks = {
				on: (hook, callback, options) => {
					/**
					* @note An already-aborted signal would never fire its 'abort' event,
					* leaving the hook registered indefinitely. Skip registration entirely.
					*/
					if (options?.signal?.aborted) return;
					if (options?.once) {
						const original = callback;
						const wrapper = ((...args) => {
							this.#deleteHookListener(hook, wrapper);
							return original(...args);
						});
						callback = wrapper;
					}
					this.#hookListeners.append(hook, callback);
					if (options) this.#hookListenerOptions.set(callback, options);
					if (options?.signal) {
						const { signal } = options;
						const onAbort = () => {
							this.#deleteHookListener(hook, callback);
						};
						signal.addEventListener("abort", onAbort, { once: true });
						this.#hookListenerAbortCleanups.set(callback, () => {
							signal.removeEventListener("abort", onAbort);
						});
					}
				},
				removeListener: (hook, callback) => {
					this.#deleteHookListener(hook, callback);
				}
			};
		}
		#deleteHookListener(hook, callback) {
			this.#hookListeners.delete(hook, callback);
			const cleanup = this.#hookListenerAbortCleanups.get(callback);
			if (cleanup) {
				cleanup();
				this.#hookListenerAbortCleanups.delete(callback);
			}
		}
		#deleteListener(type, listener) {
			const removed = this.#listeners.delete(type, listener);
			const cleanup = this.#listenerAbortCleanups.get(listener);
			if (cleanup) {
				cleanup();
				this.#listenerAbortCleanups.delete(listener);
			}
			return removed;
		}
		/**
		* Adds a listener for the given event type.
		*/
		on(type, listener, options) {
			this.#addListener(type, listener, options);
			return this;
		}
		/**
		* Adds a one-time listener for the given event type.
		*/
		once(type, listener, options) {
			return this.on(type, listener, {
				...options || {},
				once: true
			});
		}
		/**
		* Prepends a listener for the given event type.
		*/
		earlyOn(type, listener, options) {
			this.#addListener(type, listener, options, "prepend");
			return this;
		}
		/**
		* Prepends a one-time listener for the given event type.
		*/
		earlyOnce(type, listener, options) {
			return this.earlyOn(type, listener, {
				...options || {},
				once: true
			});
		}
		/**
		* Emits the given typed event.
		*
		* @returns {boolean} Returns `true` if the event had any listeners, `false` otherwise.
		*/
		emit(event) {
			if (this.#listeners.size === 0) return false;
			/**
			* @note Calculate matching listeners before calling them
			* since one-time listeners will self-destruct.
			*/
			const hasListeners = this.listenerCount(event.type) > 0;
			const proxiedEvent = this.#proxyEvent(event);
			for (const listener of this.#matchListeners(event.type)) {
				if (proxiedEvent.event[kPropagationStopped] != null && proxiedEvent.event[kPropagationStopped] !== this) {
					proxiedEvent.revoke();
					return false;
				}
				if (proxiedEvent.event[kImmediatePropagationStopped]) break;
				this.#callListener(proxiedEvent.event, listener);
			}
			proxiedEvent.revoke();
			return hasListeners;
		}
		/**
		* Emits the given typed event and returns a promise that resolves
		* when all the listeners for that event have settled.
		*
		* @returns {Promise<Array<Emitter.ListenerReturnType>>} A promise that resolves
		* with the return values of all listeners.
		*/
		async emitAsPromise(event) {
			if (this.#listeners.size === 0) return [];
			const pendingListeners = [];
			const proxiedEvent = this.#proxyEvent(event);
			for (const listener of this.#matchListeners(event.type)) {
				if (proxiedEvent.event[kPropagationStopped] != null && proxiedEvent.event[kPropagationStopped] !== this) {
					proxiedEvent.revoke();
					return [];
				}
				if (proxiedEvent.event[kImmediatePropagationStopped]) break;
				const returnValue = await Promise.resolve(this.#callListener(proxiedEvent.event, listener));
				if (!this.#isTypelessListener(listener)) pendingListeners.push(returnValue);
			}
			proxiedEvent.revoke();
			return Promise.allSettled(pendingListeners).then((results) => {
				return results.map((result) => result.status === "fulfilled" ? result.value : result.reason);
			});
		}
		/**
		* Emits the given event and returns a generator that yields
		* the result of each listener in the order of their registration.
		* This way, you stop exhausting the listeners once you get the expected value.
		*/
		*emitAsGenerator(event) {
			if (this.#listeners.size === 0) return;
			const proxiedEvent = this.#proxyEvent(event);
			for (const listener of this.#matchListeners(event.type)) {
				if (proxiedEvent.event[kPropagationStopped] != null && proxiedEvent.event[kPropagationStopped] !== this) {
					proxiedEvent.revoke();
					return;
				}
				if (proxiedEvent.event[kImmediatePropagationStopped]) break;
				const returnValue = this.#callListener(proxiedEvent.event, listener);
				if (!this.#isTypelessListener(listener)) yield returnValue;
			}
			proxiedEvent.revoke();
		}
		/**
		* Removes a listener for the given event type.
		*/
		removeListener(type, listener) {
			const options = this.#listenerOptions.get(listener);
			if (!this.#deleteListener(type, listener)) return;
			/**
			* @note Snapshot the hook list before iterating so a hook that removes
			* another `removeListener` hook can't shift the live array mid-iteration.
			*/
			for (const hook of this.#hookListeners.get("removeListener").slice()) hook(type, listener, options);
		}
		/**
		* Removes all listeners for the given event type.
		* If no event type is provided, removes all existing listeners.
		*/
		removeAllListeners(type) {
			if (type == null) {
				for (const [listenerType, listeners$1] of this.#listeners.entries()) while (listeners$1.length > 0) this.removeListener(listenerType, listeners$1[0]);
				for (const [hookType, hookListener] of [...this.#hookListeners]) if (!this.#hookListenerOptions.get(hookListener)?.persist) this.#deleteHookListener(hookType, hookListener);
				return;
			}
			const listeners = this.listeners(type);
			while (listeners.length > 0) this.removeListener(type, listeners[0]);
		}
		/**
		* Returns the list of listeners for the given event type.
		* If no even type is provided, returns all listeners.
		*/
		listeners(type) {
			if (type == null) return this.#listeners.getAll();
			return this.#listeners.get(type);
		}
		/**
		* Returns the number of listeners for the given event type.
		* If no even type is provided, returns the total number of listeners.
		*/
		listenerCount(type) {
			if (type == null) return this.#listeners.size;
			return this.listeners(type).length;
		}
		#addListener(type, listener, options, insertMode = "append") {
			/**
			* @note An already-aborted signal would never fire its 'abort' event,
			* leaving the listener registered indefinitely. Skip registration entirely.
			*/
			if (options?.signal?.aborted) return;
			for (const hook of this.#hookListeners.get("newListener").slice()) hook(type, listener, options);
			if (type === "*") this.#typelessListeners.add(listener);
			if (insertMode === "prepend") this.#listeners.prepend(type, listener);
			else this.#listeners.append(type, listener);
			if (options) {
				this.#listenerOptions.set(listener, options);
				if (options.signal) {
					const { signal } = options;
					const onAbort = () => {
						this.removeListener(type, listener);
					};
					signal.addEventListener("abort", onAbort, { once: true });
					this.#listenerAbortCleanups.set(listener, () => {
						signal.removeEventListener("abort", onAbort);
					});
				}
			}
		}
		#proxyEvent(event) {
			const { stopPropagation } = event;
			event.stopPropagation = () => {
				event[kPropagationStopped] = this;
				stopPropagation.call(event);
			};
			return {
				event,
				revoke() {
					event.stopPropagation = stopPropagation;
				}
			};
		}
		#callListener(event, listener) {
			for (const hook of this.#hookListeners.get("beforeEmit").slice()) if (hook(event) === false) return;
			const returnValue = listener.call(this, event);
			const options = this.#listenerOptions.get(listener);
			if (options?.once) {
				const type = this.#isTypelessListener(listener) ? "*" : event.type;
				if (this.#deleteListener(type, listener)) for (const hook of this.#hookListeners.get("removeListener").slice()) hook(type, listener, options);
			}
			return returnValue;
		}
		/**
		* Return a list of all event listeners relevant for the given event type.
		* This includes the explicit event listeners and also typeless event listeners.
		*
		* @note Snapshot the matching listeners before yielding. Listeners can add or
		* remove other listeners during emission (e.g. `earlyOn` unshifts `#list`),
		* which would otherwise shift the live iterator and re-yield prior entries.
		*/
		*#matchListeners(type) {
			const snapshot = [];
			for (const [key, listener] of this.#listeners) if (key === "*" || key === type) snapshot.push(listener);
			yield* snapshot;
		}
		#isTypelessListener(listener) {
			return this.#typelessListeners.has(listener);
		}
	};
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/create-request-id-YobUnJNO.js
	var __create = Object.create;
	var __defProp = Object.defineProperty;
	var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
	var __getOwnPropNames = Object.getOwnPropertyNames;
	var __getProtoOf = Object.getPrototypeOf;
	var __hasOwnProp = Object.prototype.hasOwnProperty;
	var __commonJSMin = (cb, mod) => () => (mod || (cb((mod = { exports: {} }).exports, mod), cb = null), mod.exports);
	var __copyProps = (to, from, except, desc) => {
		if (from && typeof from === "object" || typeof from === "function") for (var keys = __getOwnPropNames(from), i = 0, n = keys.length, key; i < n; i++) {
			key = keys[i];
			if (!__hasOwnProp.call(to, key) && key !== except) __defProp(to, key, {
				get: ((k) => from[k]).bind(null, key),
				enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable
			});
		}
		return to;
	};
	var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(isNodeMode || !mod || !mod.__esModule || !__hasOwnProp.call(mod, "default") ? __defProp(target, "default", {
		value: mod,
		enumerable: true
	}) : target, mod));
	var Disposable$1 = class {
		constructor() {
			this.subscriptions = [];
		}
		dispose() {
			let subscription;
			while (subscription = this.subscriptions.pop()) subscription();
		}
	};
	var require_ms = /* @__PURE__ */ __commonJSMin(((exports, module) => {
		/**
		* Helpers.
		*/
		var s = 1e3;
		var m = s * 60;
		var h = m * 60;
		var d = h * 24;
		var w = d * 7;
		var y = d * 365.25;
		/**
		* Parse or format the given `val`.
		*
		* Options:
		*
		*  - `long` verbose formatting [false]
		*
		* @param {String|Number} val
		* @param {Object} [options]
		* @throws {Error} throw an error if val is not a non-empty string or a number
		* @return {String|Number}
		* @api public
		*/
		module.exports = function(val, options) {
			options = options || {};
			var type = typeof val;
			if (type === "string" && val.length > 0) return parse(val);
			else if (type === "number" && isFinite(val)) return options.long ? fmtLong(val) : fmtShort(val);
			throw new Error("val is not a non-empty string or a valid number. val=" + JSON.stringify(val));
		};
		/**
		* Parse the given `str` and return milliseconds.
		*
		* @param {String} str
		* @return {Number}
		* @api private
		*/
		function parse(str) {
			str = String(str);
			if (str.length > 100) return;
			var match = /^(-?(?:\d+)?\.?\d+) *(milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w|years?|yrs?|y)?$/i.exec(str);
			if (!match) return;
			var n = parseFloat(match[1]);
			switch ((match[2] || "ms").toLowerCase()) {
				case "years":
				case "year":
				case "yrs":
				case "yr":
				case "y": return n * y;
				case "weeks":
				case "week":
				case "w": return n * w;
				case "days":
				case "day":
				case "d": return n * d;
				case "hours":
				case "hour":
				case "hrs":
				case "hr":
				case "h": return n * h;
				case "minutes":
				case "minute":
				case "mins":
				case "min":
				case "m": return n * m;
				case "seconds":
				case "second":
				case "secs":
				case "sec":
				case "s": return n * s;
				case "milliseconds":
				case "millisecond":
				case "msecs":
				case "msec":
				case "ms": return n;
				default: return;
			}
		}
		/**
		* Short format for `ms`.
		*
		* @param {Number} ms
		* @return {String}
		* @api private
		*/
		function fmtShort(ms) {
			var msAbs = Math.abs(ms);
			if (msAbs >= d) return Math.round(ms / d) + "d";
			if (msAbs >= h) return Math.round(ms / h) + "h";
			if (msAbs >= m) return Math.round(ms / m) + "m";
			if (msAbs >= s) return Math.round(ms / s) + "s";
			return ms + "ms";
		}
		/**
		* Long format for `ms`.
		*
		* @param {Number} ms
		* @return {String}
		* @api private
		*/
		function fmtLong(ms) {
			var msAbs = Math.abs(ms);
			if (msAbs >= d) return plural(ms, msAbs, d, "day");
			if (msAbs >= h) return plural(ms, msAbs, h, "hour");
			if (msAbs >= m) return plural(ms, msAbs, m, "minute");
			if (msAbs >= s) return plural(ms, msAbs, s, "second");
			return ms + " ms";
		}
		/**
		* Pluralization helper.
		*/
		function plural(ms, msAbs, n, name) {
			var isPlural = msAbs >= n * 1.5;
			return Math.round(ms / n) + " " + name + (isPlural ? "s" : "");
		}
	}));
	var require_common = /* @__PURE__ */ __commonJSMin(((exports, module) => {
		/**
		* This is the common logic for both the Node.js and web browser
		* implementations of `debug()`.
		*/
		function setup(env) {
			createDebug.debug = createDebug;
			createDebug.default = createDebug;
			createDebug.coerce = coerce;
			createDebug.disable = disable;
			createDebug.enable = enable;
			createDebug.enabled = enabled;
			createDebug.humanize = require_ms();
			createDebug.destroy = destroy;
			Object.keys(env).forEach((key) => {
				createDebug[key] = env[key];
			});
			/**
			* The currently active debug mode names, and names to skip.
			*/
			createDebug.names = [];
			createDebug.skips = [];
			/**
			* Map of special "%n" handling functions, for the debug "format" argument.
			*
			* Valid key names are a single, lower or upper-case letter, i.e. "n" and "N".
			*/
			createDebug.formatters = {};
			/**
			* Selects a color for a debug namespace
			* @param {String} namespace The namespace string for the debug instance to be colored
			* @return {Number|String} An ANSI color code for the given namespace
			* @api private
			*/
			function selectColor(namespace) {
				let hash = 0;
				for (let i = 0; i < namespace.length; i++) {
					hash = (hash << 5) - hash + namespace.charCodeAt(i);
					hash |= 0;
				}
				return createDebug.colors[Math.abs(hash) % createDebug.colors.length];
			}
			createDebug.selectColor = selectColor;
			/**
			* Create a debugger with the given `namespace`.
			*
			* @param {String} namespace
			* @return {Function}
			* @api public
			*/
			function createDebug(namespace) {
				let prevTime;
				let enableOverride = null;
				let namespacesCache;
				let enabledCache;
				function debug(...args) {
					if (!debug.enabled) return;
					const self = debug;
					const curr = Number(/* @__PURE__ */ new Date());
					self.diff = curr - (prevTime || curr);
					self.prev = prevTime;
					self.curr = curr;
					prevTime = curr;
					args[0] = createDebug.coerce(args[0]);
					if (typeof args[0] !== "string") args.unshift("%O");
					let index = 0;
					args[0] = args[0].replace(/%([a-zA-Z%])/g, (match, format) => {
						if (match === "%%") return "%";
						index++;
						const formatter = createDebug.formatters[format];
						if (typeof formatter === "function") {
							const val = args[index];
							match = formatter.call(self, val);
							args.splice(index, 1);
							index--;
						}
						return match;
					});
					createDebug.formatArgs.call(self, args);
					(self.log || createDebug.log).apply(self, args);
				}
				debug.namespace = namespace;
				debug.useColors = createDebug.useColors();
				debug.color = createDebug.selectColor(namespace);
				debug.extend = extend;
				debug.destroy = createDebug.destroy;
				Object.defineProperty(debug, "enabled", {
					enumerable: true,
					configurable: false,
					get: () => {
						if (enableOverride !== null) return enableOverride;
						if (namespacesCache !== createDebug.namespaces) {
							namespacesCache = createDebug.namespaces;
							enabledCache = createDebug.enabled(namespace);
						}
						return enabledCache;
					},
					set: (v) => {
						enableOverride = v;
					}
				});
				if (typeof createDebug.init === "function") createDebug.init(debug);
				return debug;
			}
			function extend(namespace, delimiter) {
				const newDebug = createDebug(this.namespace + (typeof delimiter === "undefined" ? ":" : delimiter) + namespace);
				newDebug.log = this.log;
				return newDebug;
			}
			/**
			* Enables a debug mode by namespaces. This can include modes
			* separated by a colon and wildcards.
			*
			* @param {String} namespaces
			* @api public
			*/
			function enable(namespaces) {
				createDebug.save(namespaces);
				createDebug.namespaces = namespaces;
				createDebug.names = [];
				createDebug.skips = [];
				const split = (typeof namespaces === "string" ? namespaces : "").trim().replace(/\s+/g, ",").split(",").filter(Boolean);
				for (const ns of split) if (ns[0] === "-") createDebug.skips.push(ns.slice(1));
				else createDebug.names.push(ns);
			}
			/**
			* Checks if the given string matches a namespace template, honoring
			* asterisks as wildcards.
			*
			* @param {String} search
			* @param {String} template
			* @return {Boolean}
			*/
			function matchesTemplate(search, template) {
				let searchIndex = 0;
				let templateIndex = 0;
				let starIndex = -1;
				let matchIndex = 0;
				while (searchIndex < search.length) if (templateIndex < template.length && (template[templateIndex] === search[searchIndex] || template[templateIndex] === "*")) {
					if (template[templateIndex] === "*") {
						starIndex = templateIndex;
						matchIndex = searchIndex;
						templateIndex++;
					} else {
						searchIndex++;
						templateIndex++;
					}
				} else if (starIndex !== -1) {
					templateIndex = starIndex + 1;
					matchIndex++;
					searchIndex = matchIndex;
				} else return false;
				while (templateIndex < template.length && template[templateIndex] === "*") templateIndex++;
				return templateIndex === template.length;
			}
			/**
			* Disable debug output.
			*
			* @return {String} namespaces
			* @api public
			*/
			function disable() {
				const namespaces = [...createDebug.names, ...createDebug.skips.map((namespace) => "-" + namespace)].join(",");
				createDebug.enable("");
				return namespaces;
			}
			/**
			* Returns true if the given mode name is enabled, false otherwise.
			*
			* @param {String} name
			* @return {Boolean}
			* @api public
			*/
			function enabled(name) {
				for (const skip of createDebug.skips) if (matchesTemplate(name, skip)) return false;
				for (const ns of createDebug.names) if (matchesTemplate(name, ns)) return true;
				return false;
			}
			/**
			* Coerce `val`.
			*
			* @param {Mixed} val
			* @return {Mixed}
			* @api private
			*/
			function coerce(val) {
				if (val instanceof Error) return val.stack || val.message;
				return val;
			}
			/**
			* XXX DO NOT USE. This is a temporary stub function.
			* XXX It WILL be removed in the next major release.
			*/
			function destroy() {
				console.warn("Instance method `debug.destroy()` is deprecated and no longer does anything. It will be removed in the next major version of `debug`.");
			}
			createDebug.enable(createDebug.load());
			return createDebug;
		}
		module.exports = setup;
	}));
	var import_browser = /* @__PURE__ */ __toESM((/* @__PURE__ */ __commonJSMin(((exports, module) => {
		/**
		* This is the web browser implementation of `debug()`.
		*/
		exports.formatArgs = formatArgs;
		exports.save = save;
		exports.load = load;
		exports.useColors = useColors;
		exports.storage = localstorage();
		exports.destroy = (() => {
			let warned = false;
			return () => {
				if (!warned) {
					warned = true;
					console.warn("Instance method `debug.destroy()` is deprecated and no longer does anything. It will be removed in the next major version of `debug`.");
				}
			};
		})();
		/**
		* Colors.
		*/
		exports.colors = [
			"#0000CC",
			"#0000FF",
			"#0033CC",
			"#0033FF",
			"#0066CC",
			"#0066FF",
			"#0099CC",
			"#0099FF",
			"#00CC00",
			"#00CC33",
			"#00CC66",
			"#00CC99",
			"#00CCCC",
			"#00CCFF",
			"#3300CC",
			"#3300FF",
			"#3333CC",
			"#3333FF",
			"#3366CC",
			"#3366FF",
			"#3399CC",
			"#3399FF",
			"#33CC00",
			"#33CC33",
			"#33CC66",
			"#33CC99",
			"#33CCCC",
			"#33CCFF",
			"#6600CC",
			"#6600FF",
			"#6633CC",
			"#6633FF",
			"#66CC00",
			"#66CC33",
			"#9900CC",
			"#9900FF",
			"#9933CC",
			"#9933FF",
			"#99CC00",
			"#99CC33",
			"#CC0000",
			"#CC0033",
			"#CC0066",
			"#CC0099",
			"#CC00CC",
			"#CC00FF",
			"#CC3300",
			"#CC3333",
			"#CC3366",
			"#CC3399",
			"#CC33CC",
			"#CC33FF",
			"#CC6600",
			"#CC6633",
			"#CC9900",
			"#CC9933",
			"#CCCC00",
			"#CCCC33",
			"#FF0000",
			"#FF0033",
			"#FF0066",
			"#FF0099",
			"#FF00CC",
			"#FF00FF",
			"#FF3300",
			"#FF3333",
			"#FF3366",
			"#FF3399",
			"#FF33CC",
			"#FF33FF",
			"#FF6600",
			"#FF6633",
			"#FF9900",
			"#FF9933",
			"#FFCC00",
			"#FFCC33"
		];
		/**
		* Currently only WebKit-based Web Inspectors, Firefox >= v31,
		* and the Firebug extension (any Firefox version) are known
		* to support "%c" CSS customizations.
		*
		* TODO: add a `localStorage` variable to explicitly enable/disable colors
		*/
		function useColors() {
			if (typeof window !== "undefined" && window.process && (window.process.type === "renderer" || window.process.__nwjs)) return true;
			if (typeof navigator !== "undefined" && navigator.userAgent && navigator.userAgent.toLowerCase().match(/(edge|trident)\/(\d+)/)) return false;
			let m;
			return typeof document !== "undefined" && document.documentElement && document.documentElement.style && document.documentElement.style.WebkitAppearance || typeof window !== "undefined" && window.console && (window.console.firebug || window.console.exception && window.console.table) || typeof navigator !== "undefined" && navigator.userAgent && (m = navigator.userAgent.toLowerCase().match(/firefox\/(\d+)/)) && parseInt(m[1], 10) >= 31 || typeof navigator !== "undefined" && navigator.userAgent && navigator.userAgent.toLowerCase().match(/applewebkit\/(\d+)/);
		}
		/**
		* Colorize log arguments if enabled.
		*
		* @api public
		*/
		function formatArgs(args) {
			args[0] = (this.useColors ? "%c" : "") + this.namespace + (this.useColors ? " %c" : " ") + args[0] + (this.useColors ? "%c " : " ") + "+" + module.exports.humanize(this.diff);
			if (!this.useColors) return;
			const c = "color: " + this.color;
			args.splice(1, 0, c, "color: inherit");
			let index = 0;
			let lastC = 0;
			args[0].replace(/%[a-zA-Z%]/g, (match) => {
				if (match === "%%") return;
				index++;
				if (match === "%c") lastC = index;
			});
			args.splice(lastC, 0, c);
		}
		/**
		* Invokes `console.debug()` when available.
		* No-op when `console.debug` is not a "function".
		* If `console.debug` is not available, falls back
		* to `console.log`.
		*
		* @api public
		*/
		exports.log = console.debug || console.log || (() => {});
		/**
		* Save `namespaces`.
		*
		* @param {String} namespaces
		* @api private
		*/
		function save(namespaces) {
			try {
				if (namespaces) exports.storage.setItem("debug", namespaces);
				else exports.storage.removeItem("debug");
			} catch (error) {}
		}
		/**
		* Load `namespaces`.
		*
		* @return {String} returns the previously persisted debug modes
		* @api private
		*/
		function load() {
			let r;
			try {
				r = exports.storage.getItem("debug") || exports.storage.getItem("DEBUG");
			} catch (error) {}
			if (!r && typeof process !== "undefined" && "env" in process) r = process.env.DEBUG;
			return r;
		}
		/**
		* Localstorage attempts to return the localstorage.
		*
		* This is necessary because safari throws
		* when a user disables cookies/localstorage
		* and you attempt to access it.
		*
		* @return {LocalStorage}
		* @api private
		*/
		function localstorage() {
			try {
				return localStorage;
			} catch (error) {}
		}
		module.exports = require_common()(exports);
		const { formatters } = module.exports;
		/**
		* Map %j to `JSON.stringify()`, since no Web Inspectors do that by default.
		*/
		formatters.j = function(v) {
			try {
				return JSON.stringify(v);
			} catch (error) {
				return "[UnexpectedJSONParseError]: " + error.message;
			}
		};
	})))(), 1);
	const LOG_TIMESTAMP_REGEXP = /\d{2}:\d{2}:\d{2}\.\d{3}/;
	function normalizeNamespace(namespace) {
		return namespace.split(":").map((segment) => {
			return segment.replace(/([a-z0-9])([A-Z])/g, "$1-$2").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
		}).filter(Boolean).join(":");
	}
	function getTimestamp$1() {
		return (/* @__PURE__ */ new Date()).toISOString().slice(11, 23);
	}
	async function readBody(message) {
		if (message.body == null) return null;
		try {
			return await message.clone().text();
		} catch {
			return null;
		}
	}
	function formatHeaders(headers) {
		return Array.from(headers.entries()).map(([name, value]) => {
			return `${name}: ${value}`;
		});
	}
	async function formatHttpMessage(startLine, message) {
		const lines = [startLine, ...formatHeaders(message.headers)];
		const body = await readBody(message);
		lines.push("", body ?? "");
		return lines.join("\n");
	}
	async function formatRequest(request) {
		return formatHttpMessage(`${request.method} ${request.url}`, request);
	}
	async function formatResponse(response) {
		const statusText = response.statusText ? ` ${response.statusText}` : "";
		return formatHttpMessage(`HTTP ${response.status}${statusText}`, response);
	}
	function formatLogArguments(arguments_) {
		const message = arguments_[0];
		if (typeof message === "string") {
			const messageWithoutDebugTimestamp = message.replace(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z /, "");
			const timestampMatch = messageWithoutDebugTimestamp.match(LOG_TIMESTAMP_REGEXP);
			if (!timestampMatch || timestampMatch.index === void 0) {
				arguments_[0] = messageWithoutDebugTimestamp;
				return;
			}
			const messagePrefix = messageWithoutDebugTimestamp.slice(0, timestampMatch.index).trim();
			const messageBody = messageWithoutDebugTimestamp.slice(timestampMatch.index + timestampMatch[0].length).trimStart();
			arguments_[0] = `${timestampMatch[0]} ${messagePrefix} ${messageBody}`;
		}
	}
	function useConciseTimestamp(logger) {
		logger.log = (...arguments_) => {
			formatLogArguments(arguments_);
			import_browser.log(...arguments_);
		};
	}
	function isVerboseLoggingEnabled() {
		if (typeof process !== "undefined" && process.env.DEBUG_LEVEL === "verbose") return true;
		/**
		* @note Consult the localStorage only in browser-like environments.
		* In Node.js 26+, reading "globalThis.localStorage" without the
		* "--localstorage-file" flag set emits an experimental warning
		* (a try/catch cannot suppress it). Node.js consumers control the
		* log level via the "DEBUG_LEVEL" environment variable above.
		*/
		if (typeof document === "undefined") return false;
		try {
			return globalThis.localStorage?.getItem("debugLevel") === "verbose";
		} catch {
			return false;
		}
	}
	function createLogger(namespace) {
		const normalizedNamespace = normalizeNamespace(namespace);
		const logger = (0, import_browser.default)(`interceptors:${normalizedNamespace}`);
		Reflect.set(logger, "useColors", true);
		useConciseTimestamp(logger);
		return {
			info(message, ...positionals) {
				logger(`${getTimestamp$1()} ${message}`, ...positionals);
			},
			verbose(message, ...positionals) {
				if (!isVerboseLoggingEnabled()) return;
				logger(`${getTimestamp$1()} ${message}`, ...positionals);
			},
			isEnabled(level) {
				return logger.enabled && (level === "default" || isVerboseLoggingEnabled());
			}
		};
	}
	const interceptorsRegistry = globalThis.__MSW_INTERCEPTORS_REGISTRY ??= /* @__PURE__ */ new Map();
	var Interceptor = class extends Disposable$1 {
		#owners;
		static singleton(InterceptorClass) {
			const symbol = InterceptorClass.symbol;
			const existing = interceptorsRegistry.get(symbol);
			if (existing instanceof InterceptorClass) return existing;
			const newInstance = new InterceptorClass();
			interceptorsRegistry.set(symbol, newInstance);
			return newInstance;
		}
		constructor() {
			super();
			this.on = (type, listener, options) => {
				return this.emitter.on(type, listener, options);
			};
			this.once = (type, listener, options) => {
				return this.emitter.once(type, listener, options);
			};
			this.listeners = (type) => {
				return this.emitter.listeners(type);
			};
			this.listenerCount = (type) => {
				return this.emitter.listenerCount(type);
			};
			this.removeListener = (type, listener) => {
				return this.emitter.removeListener(type, listener);
			};
			this.removeAllListeners = (type) => {
				this.logger.info("removeAllListeners %o", { eventType: type ?? "*" });
				return this.emitter.removeAllListeners(type);
			};
			this.#owners = /* @__PURE__ */ new Set();
			this.readyState = "INACTIVE";
			this.emitter = new Emitter();
			this.logger = createLogger(this.#getLoggerNamespace());
		}
		apply(owner = this) {
			if (this.#owners.has(owner)) return;
			if (this.readyState !== "ACTIVE" && !this.predicate()) return;
			this.#owners.add(owner);
			if (this.readyState === "ACTIVE") return;
			try {
				this.setup();
				this.readyState = "ACTIVE";
				this.logger.info("apply");
			} catch (error) {
				this.dispose(owner);
				throw error;
			}
		}
		dispose(owner = this) {
			if (!this.#owners.delete(owner)) return;
			if (this.#owners.size > 0) return;
			super.dispose();
			this.emitter.removeAllListeners();
			this.readyState = "DISPOSED";
			this.logger.info("disable");
		}
		#getLoggerNamespace() {
			const symbolDescription = this.constructor.symbol?.description;
			if (symbolDescription) return symbolDescription.replace(/-interceptor$/, "");
			return this.constructor.name.replace(/Interceptor$/, "");
		}
	};
	/**
	* Generate a random ID string to represent a request.
	* @example
	* createRequestId()
	* // "f774b6c9c600f"
	*/
	function createRequestId() {
		return Math.random().toString(16).slice(2);
	}
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/fetch-utils-C6P6gLLo.js
	var InterceptorError = class InterceptorError extends Error {
		constructor(message) {
			super(message);
			this.name = "InterceptorError";
			Object.setPrototypeOf(this, InterceptorError.prototype);
		}
	};
	var RequestController = class RequestController {
		static {
			this.PENDING = 0;
		}
		static {
			this.PASSTHROUGH = 1;
		}
		static {
			this.RESPONSE = 2;
		}
		static {
			this.ERROR = 3;
		}
		#handled;
		constructor(request, source, options) {
			this.request = request;
			this.source = source;
			this.options = options;
			this.readyState = RequestController.PENDING;
			this.#handled = Promise.withResolvers();
			this.handled = this.#handled.promise;
		}
		/**
		* Perform this request as-is.
		*/
		async passthrough() {
			invariant$1.as(InterceptorError, this.readyState === RequestController.PENDING, "Failed to passthrough the \"%s %s\" request: the request has already been handled", this.request.method, this.request.url);
			this.readyState = RequestController.PASSTHROUGH;
			if (this.options) this.options.logger.info("[%s] passthrough", this.options.requestId);
			await this.source.passthrough();
			this.#handled.resolve();
		}
		/**
		* Respond to this request with the given `Response` instance.
		*
		* @example
		* controller.respondWith(new Response())
		* controller.respondWith(Response.json({ id }))
		* controller.respondWith(Response.error())
		*/
		respondWith(response) {
			invariant$1.as(InterceptorError, this.readyState === RequestController.PENDING, "Failed to respond to the \"%s %s\" request with \"%d %s\": the request has already been handled (%d)", this.request.method, this.request.url, response.status, response.statusText || "OK", this.readyState);
			this.readyState = RequestController.RESPONSE;
			if (this.options?.logger.isEnabled("default")) {
				const { logger, requestId } = this.options;
				formatResponse(response).then((message) => {
					logger.info("[%s] mocked %s", requestId, message);
				});
			}
			this.#handled.resolve();
			/**
			* @note Although `source.respondWith()` is potentially asynchronous,
			* do NOT await it for backward-compatibility. Awaiting it will short-circuit
			* the request listener invocation as soon as a listener responds to a request.
			* Ideally, that's what we want, but that's not what we promise the user.
			*/
			this.source.respondWith(response);
		}
		/**
		* Error this request with the given reason.
		*
		* @example
		* controller.errorWith()
		* controller.errorWith(new Error('Oops!'))
		* controller.errorWith({ message: 'Oops!'})
		*/
		errorWith(reason) {
			invariant$1.as(InterceptorError, this.readyState === RequestController.PENDING, "Failed to error the \"%s %s\" request with \"%s\": the request has already been handled (%d)", this.request.method, this.request.url, reason?.toString(), this.readyState);
			this.readyState = RequestController.ERROR;
			if (this.options) this.options.logger.info("[%s] error %o", this.options.requestId, reason);
			this.source.errorWith(reason);
			this.#handled.resolve();
		}
	};
	const kRawHeaders = Symbol("kRawHeaders");
	/**
	* Define the raw headers symbol on the given `Headers` instance.
	* If the symbol already exists, it gets overridden.
	*/
	function defineRawHeadersSymbol(headers, rawHeaders) {
		Object.defineProperty(headers, kRawHeaders, {
			value: rawHeaders,
			enumerable: false,
			configurable: true
		});
	}
	function getRawFetchHeaders(headers) {
		if (!Reflect.has(headers, kRawHeaders)) return Array.from(headers.entries());
		const rawHeaders = Reflect.get(headers, kRawHeaders);
		return rawHeaders.length > 0 ? rawHeaders : Array.from(headers.entries());
	}
	function copyRawHeaders(source, destination) {
		const rawHeaders = [...getRawFetchHeaders(source)];
		if (rawHeaders.length === 0) return;
		/**
		* @note Add headers from trhe destination that raw headers from the source
		* don't have. Undici automatically appends a "Content-Type" header for responses
		* and, for some reason, that change is not recorded. This preserves it.
		*/
		for (const [name, value] of destination) if (rawHeaders.every((header) => header[0].toLowerCase() !== name.toLowerCase())) rawHeaders.push([name, value]);
		defineRawHeadersSymbol(destination, rawHeaders);
	}
	/**
	* Returns the value behind the symbol with the given name.
	*/
	function getValueBySymbol(symbolName, source) {
		const symbol = Object.getOwnPropertySymbols(source).find((symbol) => {
			return symbol.description === symbolName;
		});
		if (symbol) return Reflect.get(source, symbol);
	}
	/**
	* Determines if a given value is an instance of object.
	*/
	function isObject$2(value, loose = false) {
		return loose ? Object.prototype.toString.call(value).startsWith("[object ") : Object.prototype.toString.call(value) === "[object Object]";
	}
	/**
	* A function that validates if property access is possible on an object
	* without throwing. It returns `true` if the property access is possible
	* and `false` otherwise.
	*
	* Environments like miniflare will throw on property access on certain objects
	* like Request and Response, for unimplemented properties.
	*/
	function isPropertyAccessible(obj, key) {
		try {
			obj[key];
			return true;
		} catch {
			return false;
		}
	}
	/**
	* Creates a generic 500 Unhandled Exception response.
	*/
	function createServerErrorResponse(body) {
		return new Response(JSON.stringify(body instanceof Error ? {
			name: body.name,
			message: body.message,
			stack: body.stack
		} : body), {
			status: 500,
			statusText: "Unhandled Exception",
			headers: { "Content-Type": "application/json" }
		});
	}
	/**
	* Check if the given response is a `Response.error()`.
	*
	* @note Some environments, like Miniflare (Cloudflare) do not
	* implement the "Response.type" property and throw on its access.
	* Safely check if we can access "type" on "Response" before continuing.
	* @see https://github.com/mswjs/msw/issues/1834
	*/
	function isResponseError(response) {
		return response != null && response instanceof Response && isPropertyAccessible(response, "type") && response.type === "error";
	}
	/**
	* Check if the given value is a `Response` or a Response-like object.
	* This is different from `value instanceof Response` because it supports
	* custom `Response` constructors, like the one when using Undici directly.
	*/
	function isResponseLike(value) {
		return isObject$2(value, true) && isPropertyAccessible(value, "status") && isPropertyAccessible(value, "statusText") && isPropertyAccessible(value, "bodyUsed");
	}
	var FetchRequest = class FetchRequest extends Request {
		static #resolveProperty(input, init = {}, key) {
			return init[key] ?? (input instanceof Request ? input[key] : void 0);
		}
		/**
		* Check if the given request method is configurable.
		* @see https://fetch.spec.whatwg.org/#methods
		*/
		static isConfigurableMethod(method) {
			return method !== "CONNECT" && method !== "TRACE" && method !== "TRACK";
		}
		static isMethodWithBody(method) {
			return method !== "HEAD" && method !== "GET" && FetchRequest.isConfigurableMethod(method);
		}
		/**
		* Check if the given request `mode` is configurable.
		* @see https://fetch.spec.whatwg.org/#concept-request-mode
		*/
		static isConfigurableMode(mode) {
			return mode !== "navigate" && mode !== "websocket" && mode !== "webtransport";
		}
		constructor(input, init) {
			const method = FetchRequest.#resolveProperty(input, init, "method") || "GET";
			const safeMethod = FetchRequest.isConfigurableMethod(method) ? method : "GET";
			const hasExplicitBody = init != null && "body" in init;
			/**
			* Only include `body` in the super init when it needs to be overridden.
			* When `input` is a Request and no explicit body is in `init`, let the
			* Request constructor handle body transfer naturally so it properly
			* marks the original request's body as consumed (bodyUsed = true).
			*/
			const bodyInit = !FetchRequest.isMethodWithBody(method) ? { body: void 0 } : hasExplicitBody ? { body: init.body } : {};
			const mode = FetchRequest.#resolveProperty(input, init, "mode") ?? void 0;
			const safeMode = FetchRequest.isConfigurableMode(mode) ? mode : void 0;
			super(input, {
				...init || {},
				method: safeMethod,
				mode: safeMode,
				duplex: init?.duplex ?? (FetchRequest.isMethodWithBody(method) ? "half" : void 0),
				...bodyInit
			});
			if (method !== safeMethod) this.#setInternalProperty("method", method);
			if (method === "CONNECT") {
				const url = new URL(input instanceof Request ? input.url : input);
				let authority;
				/**
				* @note Node.js has a bug parsing raw CONNECT requests URLs like
				* "http://127.0.0.1:1337/localhost:80". It would treat "localhost:" as a protocol.
				*/
				if (url.protocol === "localhost:") authority = url.href;
				else authority = url.pathname.replace(/^\/+/, "");
				/**
				* @note Define "url" as a getter because Undici uses their own
				* logic to resolve the "request.url" property. Simply reassigning
				* its value doesn't do anything. This is a destructive action
				* but it's safe because "CONNECT" requests are forbidden per fetch.
				*/
				Object.defineProperty(this, "url", {
					get: () => authority,
					enumerable: true,
					configurable: true
				});
			}
			if (mode != null && mode !== safeMode) this.#setInternalProperty("mode", mode);
		}
		#setInternalProperty(key, value) {
			const internalState = getValueBySymbol("state", this);
			if (internalState) Reflect.set(internalState, key, value);
			else Object.defineProperty(this, key, {
				value,
				enumerable: true,
				configurable: true,
				writable: false
			});
		}
	};
	const kStatus = Symbol("kStatus");
	const kUrl = Symbol("kUrl");
	var FetchResponse = class FetchResponse extends Response {
		static from(response, init) {
			if (response instanceof FetchResponse) return response;
			if (isResponseError(response)) return response;
			const fetchResponse = new FetchResponse(response.body, {
				url: init?.url ?? response.url,
				status: init?.status || response.status,
				statusText: init?.statusText ?? response.statusText,
				headers: init?.headers ?? response.headers
			});
			copyRawHeaders(response.headers, fetchResponse.headers);
			return fetchResponse;
		}
		static {
			this.STATUS_CODES_WITHOUT_BODY = [
				101,
				103,
				204,
				205,
				304
			];
		}
		static {
			this.STATUS_CODES_WITH_REDIRECT = [
				301,
				302,
				303,
				307,
				308
			];
		}
		static isConfigurableStatusCode(status) {
			return status >= 200 && status <= 599;
		}
		static isRedirectResponse(status) {
			return FetchResponse.STATUS_CODES_WITH_REDIRECT.includes(status);
		}
		/**
		* Returns a boolean indicating whether the given response status
		* code represents a response that can have a body.
		*/
		static isResponseWithBody(status) {
			return !FetchResponse.STATUS_CODES_WITHOUT_BODY.includes(status);
		}
		static setStatus(status, response) {
			/**
			* @note Undici keeps an internal "Symbol(state)" that holds
			* the actual value of response status. Update that in Node.js.
			*/
			const internalState = getValueBySymbol("state", response);
			if (internalState) internalState.status = status;
			else Object.defineProperty(response, "status", {
				value: status,
				enumerable: true,
				configurable: true,
				writable: false
			});
			Object.defineProperty(response, kStatus, {
				value: status,
				enumerable: false
			});
		}
		static setUrl(url, response) {
			if (!url || url === "about:" || !URL.canParse(url)) return;
			const state = getValueBySymbol("state", response);
			if (state) state.urlList.push(new URL(url));
			else {
				Object.defineProperty(response, "url", {
					value: url,
					enumerable: true,
					configurable: true,
					writable: false
				});
				/**
				* @note A redefined `url` is an own property of this instance
				* and does not carry over to its clones. Forward it manually.
				* `FetchResponse` already does this in its own `clone()` method.
				*/
				if (!(response instanceof FetchResponse)) {
					const originalClone = response.clone;
					Object.defineProperty(response, "clone", {
						value: function clone() {
							const clonedResponse = originalClone.call(this);
							FetchResponse.setUrl(url, clonedResponse);
							return clonedResponse;
						},
						enumerable: false,
						configurable: true,
						writable: true
					});
				}
			}
			Object.defineProperty(response, kUrl, {
				value: url,
				enumerable: false
			});
		}
		/**
		* Parses the given raw HTTP headers into a Fetch API `Headers` instance.
		*/
		static parseRawHeaders(rawHeaders) {
			const headers = new Headers();
			for (let line = 0; line < rawHeaders.length; line += 2) headers.append(rawHeaders[line], rawHeaders[line + 1]);
			return headers;
		}
		/**
		* Safely clones the given `Response`.
		* Coerces response clone exceptions into 500 mocked responses.
		* Handy in the environments that introduce arbitrary response
		* cloning restrictions, like "101 Switching Protocols" cloning
		* in "miniflare".
		*/
		static clone(response) {
			try {
				return response.clone();
			} catch (error) {
				return Response.json(error instanceof Error ? {
					name: error.name,
					message: error.message,
					stack: error.stack
				} : {}, {
					status: 500,
					statusText: "Unclonable Response"
				});
			}
		}
		#status;
		#url;
		constructor(body, init = {}) {
			const status = init.status ?? 200;
			const safeStatus = FetchResponse.isConfigurableStatusCode(status) ? status : 200;
			const finalBody = FetchResponse.isResponseWithBody(status) ? body : null;
			super(finalBody, {
				status: safeStatus,
				statusText: init.statusText,
				headers: init.headers
			});
			/**
			* Since Node.js v24, Undici stores the Response state in an inaccessible field "#state".
			* Forward the modified status/URL to the cloned response manually.
			* @see https://github.com/nodejs/undici/blob/f734c87280e626c75f59aad55b65eb6a89cef392/lib/web/fetch/response.js#L242
			*/
			if (status !== safeStatus) FetchResponse.setStatus(status, this);
			FetchResponse.setUrl(init.url, this);
		}
		clone() {
			const clonedResponse = super.clone();
			const customStatus = Reflect.get(this, kStatus);
			if (customStatus) FetchResponse.setStatus(customStatus, clonedResponse);
			const customUrl = Reflect.get(this, kUrl);
			if (customUrl) FetchResponse.setUrl(customUrl, clonedResponse);
			return clonedResponse;
		}
	};
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/buffer-utils-DJj7YzLG.js
	const encoder = new TextEncoder();
	function encodeBuffer(text) {
		return encoder.encode(text);
	}
	function decodeBuffer(buffer, encoding) {
		return new TextDecoder(encoding).decode(buffer);
	}
	/**
	* Create an `ArrayBuffer` from the given `Uint8Array`.
	* Takes the byte offset into account to produce the right buffer
	* in the case when the buffer is bigger than the data view.
	*/
	function toArrayBuffer(array) {
		return array.buffer.slice(array.byteOffset, array.byteOffset + array.byteLength);
	}
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/resolve-web-socket-url-CSvNPLGi.js
	/**
	* Resolve potentially relative WebSocket URLs the same way
	* the browser does (replace the protocol, use the origin, etc).
	*
	* @see https://websockets.spec.whatwg.org//#dom-websocket-websocket
	*/
	function resolveWebSocketUrl(url) {
		if (typeof url === "string") return resolveWebSocketUrl(new URL(url, typeof location !== "undefined" ? location.href : void 0));
		if (url.protocol === "http:") url.protocol = "ws:";
		else if (url.protocol === "https:") url.protocol = "wss:";
		if (url.protocol !== "ws:" && url.protocol !== "wss:")
 /**
		* @note These errors are modeled after the browser errors.
		* The exact error messages aren't provided in the specification.
		* Node.js uses more obscure error messages that I don't wish to replicate.
		*/
		throw new SyntaxError(`Failed to construct 'WebSocket': The URL's scheme must be either 'http', 'https', 'ws', or 'wss'. '${url.protocol}' is not allowed.`);
		if (url.hash !== "") throw new SyntaxError(`Failed to construct 'WebSocket': The URL contains a fragment identifier ('${url.hash}'). Fragment identifiers are not allowed in WebSocket URLs.`);
		return url.href;
	}
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/index.js
	function addEventBridge(interceptor, type, listener) {
		interceptor.on(type, listener);
	}
	function removeEventBridge(interceptor, type, listener) {
		interceptor.removeListener(type, listener);
	}
	/**
	* A batch interceptor that exposes a single interface
	* to apply and operate with multiple interceptors at once.
	*/
	var BatchInterceptor = class extends Interceptor {
		#interceptors;
		#eventBridges;
		#forwardedEvents;
		constructor(options) {
			super();
			this.#interceptors = options.interceptors;
			this.#eventBridges = /* @__PURE__ */ new Map();
			this.#forwardedEvents = /* @__PURE__ */ new Map();
			this.emitter.hooks.on("newListener", (type) => {
				this.#ensureEventBridge(type);
			}, { persist: true });
			this.emitter.hooks.on("removeListener", (type) => {
				if (this.emitter.listenerCount(type) === 0) this.#removeEventBridge(type);
			}, { persist: true });
		}
		predicate() {
			for (const interceptor of this.#interceptors) if (interceptor["predicate"]())
 /**
			* @note If at least one of the provided interceptors suits the environment,
			* treat this batch interceptor as matching. Since all the interceptors abide
			* by the same event map, it will handle the events from any that match.
			*/
			return true;
			return false;
		}
		setup() {
			const interceptors = new Set(this.#interceptors);
			this.#forwardedEvents = /* @__PURE__ */ new Map();
			this.logger.verbose("applying batch %s with %d interceptors", this.constructor.name, interceptors.size);
			this.subscriptions.push(() => {
				this.#removeAllEventBridges();
			});
			for (const interceptor of interceptors) {
				this.logger.verbose("applying \"%s\" interceptor...", interceptor.constructor.name);
				interceptor.apply(this);
				this.logger.verbose("adding interceptor dispose subscription");
				this.subscriptions.push(() => {
					interceptor.dispose(this);
				});
			}
		}
		#ensureEventBridge(type) {
			if (this.#eventBridges.has(type)) return;
			if (type === "*") {
				this.#ensureWildcardEventBridge();
				return;
			}
			this.#ensureTypedEventBridge(type);
		}
		#ensureTypedEventBridge(type) {
			const interceptors = new Set(this.#interceptors);
			const batchEmitter = this.emitter;
			const forwardEvent = async (event) => {
				if (this.#recordForwardedEvent(event)) {
					this.logger.verbose("skipping duplicate \"%s\" event", event.type);
					return;
				}
				this.logger.verbose("forwarding \"%s\" event", event.type);
				await batchEmitter.emitAsPromise(event);
			};
			for (const interceptor of interceptors) addEventBridge(interceptor, type, forwardEvent);
			this.#eventBridges.set(type, () => {
				for (const interceptor of interceptors) removeEventBridge(interceptor, type, forwardEvent);
			});
		}
		#ensureWildcardEventBridge() {
			const interceptors = new Set(this.#interceptors);
			const batchEmitter = this.emitter;
			const forwardEvent = (event) => {
				if (this.#recordForwardedEvent(event)) {
					this.logger.verbose("skipping duplicate \"%s\" event", event.type);
					return;
				}
				this.logger.verbose("forwarding wildcard \"%s\" event", event.type);
				batchEmitter.emitAsPromise(event);
			};
			for (const interceptor of interceptors) addEventBridge(interceptor, "*", forwardEvent);
			this.#eventBridges.set("*", () => {
				for (const interceptor of interceptors) removeEventBridge(interceptor, "*", forwardEvent);
			});
		}
		#recordForwardedEvent(event) {
			const forwardedEvents = this.#forwardedEvents.get(event.type);
			if (forwardedEvents?.has(event)) return true;
			if (forwardedEvents) {
				forwardedEvents.add(event);
				return false;
			}
			this.#forwardedEvents.set(event.type, new WeakSet([event]));
			return false;
		}
		#removeEventBridge(type) {
			const disposeEventBridge = this.#eventBridges.get(type);
			if (!disposeEventBridge) return;
			disposeEventBridge();
			this.#eventBridges.delete(type);
		}
		#removeAllEventBridges() {
			for (const disposeEventBridge of this.#eventBridges.values()) disposeEventBridge();
			this.#eventBridges.clear();
		}
	};
	/**
	* Removes query parameters and hashes from a given URL.
	*/
	function getCleanUrl(url, isAbsolute = true) {
		return [isAbsolute && url.origin, url.pathname].filter(Boolean).join("");
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
		* @note Reconstruct the response because the body of an existing
		* response cannot be replaced. Use `FetchResponse` to support
		* non-standard response status codes (e.g. 101).
		*/
		const observedResponse = new FetchResponse(new ReadableStream({
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
		}), {
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
	//#region src/core/utils/internal/is-string-equal.ts
	/**
	* Performs a case-insensitive comparison of two given strings.
	*/
	function isStringEqual(actual, expected) {
		return actual.toLowerCase() === expected.toLowerCase();
	}
	//#endregion
	//#region src/core/utils/logging/get-status-code-color.ts
	/**
	* Returns a HEX color for a given response status code number.
	*/
	function getStatusCodeColor(status) {
		if (status < 300) return "#69AB32";
		if (status < 400) return "#F0BB4B";
		return "#E95F5D";
	}
	//#endregion
	//#region src/core/utils/logging/get-timestamp.ts
	/**
	* Returns a timestamp string in a "HH:MM:SS" format.
	*/
	function getTimestamp(options) {
		const now = /* @__PURE__ */ new Date();
		const timestamp = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}:${now.getSeconds().toString().padStart(2, "0")}`;
		if (options?.milliseconds) return `${timestamp}.${now.getMilliseconds().toString().padStart(3, "0")}`;
		return timestamp;
	}
	//#endregion
	//#region src/core/utils/logging/serialize-request.ts
	/**
	* Formats a mocked request for introspection in browser's console.
	*/
	async function serializeRequest(request) {
		const requestText = await request.clone().text();
		return {
			url: new URL(request.url),
			method: request.method,
			headers: Object.fromEntries(request.headers.entries()),
			body: requestText
		};
	}
	//#endregion
	//#region src/core/utils/logging/serialize-response.ts
	async function serializeResponse(response) {
		const responseClone = response.clone();
		const responseText = await responseClone.text();
		const responseStatus = responseClone.status || 200;
		return {
			status: responseStatus,
			statusText: responseClone.statusText || httpStatusMessages[responseStatus] || "OK",
			headers: Object.fromEntries(responseClone.headers.entries()),
			body: responseText
		};
	}
	//#endregion
	//#region node_modules/.pnpm/@msw+url@0.1.2/node_modules/@msw/url/build/index.mjs
	const ASTERISK = 42;
	const SLASH = 47;
	const COLON = 58;
	const QUESTION_MARK = 63;
	const PLUS = 43;
	const BACKSLASH = 92;
	const UNDERSCORE = 95;
	const OPEN_BRACKET = 91;
	const CLOSE_BRACKET = 93;
	const UPPERCASE_A = 65;
	const UPPERCASE_Z = 90;
	const MAX_INPUT_LENGTH = 8192;
	const PATTERN_CACHE_LIMIT = 1e3;
	const MAX_MATCH_STEPS = 1e5;
	const PATTERN_CACHE = /* @__PURE__ */ new Map();
	const NO_MATCH = Object.freeze({
		matches: false,
		params: Object.freeze(Object.create(null))
	});
	function isIdentStartCode(code) {
		return code >= 97 && code <= 122 || code >= 65 && code <= 90 || code === UNDERSCORE;
	}
	function isIdentCharCode(code) {
		return isIdentStartCode(code) || code >= 48 && code <= 57;
	}
	/**
	* Lowercase the case-insensitive parts of a URL — the scheme and
	* the host. Applies to both patterns and inputs so that
	* `http://EXAMPLE.com` matches `http://example.com`. The userinfo
	* (`user:pass@`), the path, and `:param` names within the host are
	* case-sensitive and preserved as-is.
	*/
	function lowercaseSchemeAndHost(url) {
		const schemeSeparatorIndex = url.indexOf("://");
		if (schemeSeparatorIndex === -1) return url;
		if (url.indexOf("/") !== schemeSeparatorIndex + 1) return url;
		const authorityStart = schemeSeparatorIndex + 3;
		let hostEnd = url.indexOf("/", authorityStart);
		if (hostEnd === -1) hostEnd = url.length;
		let needsLowercasing = false;
		for (let i = 0; i < hostEnd; i++) {
			const code = url.charCodeAt(i);
			if (code >= UPPERCASE_A && code <= UPPERCASE_Z || code > 127) {
				needsLowercasing = true;
				break;
			}
		}
		if (!needsLowercasing) return url;
		const userinfoEnd = url.lastIndexOf("@", hostEnd - 1);
		let result = "";
		let plainStart = 0;
		let inBrackets = false;
		let i = 0;
		while (i < hostEnd) {
			if (i === authorityStart && userinfoEnd >= authorityStart) {
				result += url.slice(plainStart, i).toLowerCase();
				result += url.slice(i, userinfoEnd + 1);
				i = userinfoEnd + 1;
				plainStart = i;
				continue;
			}
			const code = url.charCodeAt(i);
			if (code === OPEN_BRACKET) inBrackets = true;
			else if (code === CLOSE_BRACKET) inBrackets = false;
			else if (code === COLON && !inBrackets && i + 1 < hostEnd && isIdentStartCode(url.charCodeAt(i + 1))) {
				result += url.slice(plainStart, i).toLowerCase();
				const paramStart = i;
				i++;
				while (i < hostEnd && isIdentCharCode(url.charCodeAt(i))) i++;
				result += url.slice(paramStart, i);
				plainStart = i;
				continue;
			}
			i++;
		}
		result += url.slice(plainStart, hostEnd).toLowerCase();
		result += url.slice(hostEnd);
		return result;
	}
	function parsePatternOrGetFromCache(pattern) {
		let parsed = PATTERN_CACHE.get(pattern);
		if (parsed === void 0) {
			const normalizedPattern = lowercaseSchemeAndHost(pattern);
			const tokens = parsePattern(normalizedPattern);
			let isLiteralOnly = normalizedPattern.indexOf("\\") === -1;
			for (let i = 0; isLiteralOnly && i < tokens.length; i++) if (tokens[i].type !== 0) isLiteralOnly = false;
			const lastToken = tokens[tokens.length - 1];
			const hasTrailingSlash = lastToken !== void 0 && lastToken.type === 0 && lastToken.value.length > 0 && lastToken.value.charCodeAt(lastToken.value.length - 1) === SLASH;
			if (PATTERN_CACHE.size >= PATTERN_CACHE_LIMIT) PATTERN_CACHE.delete(PATTERN_CACHE.keys().next().value);
			parsed = {
				tokens,
				isLiteralOnly,
				hasTrailingSlash,
				normalizedPattern
			};
			PATTERN_CACHE.set(pattern, parsed);
		}
		return parsed;
	}
	function parsePattern(pattern) {
		const tokens = [];
		let i = 0;
		const length = pattern.length;
		let inBrackets = false;
		while (i < length) {
			const code = pattern.charCodeAt(i);
			if (code === BACKSLASH && i + 1 < length) {} else if (code === ASTERISK && !inBrackets) {
				tokens.push({
					type: 1,
					nextLiteral: void 0
				});
				i++;
				continue;
			} else if (code === COLON && !inBrackets && i + 1 < length && isIdentStartCode(pattern.charCodeAt(i + 1))) {
				const start = ++i;
				while (i < length && isIdentCharCode(pattern.charCodeAt(i))) i++;
				const name = pattern.slice(start, i);
				let modifier = "";
				if (i < length) {
					const mod = pattern.charCodeAt(i);
					if (mod === QUESTION_MARK || mod === PLUS || mod === ASTERISK) {
						modifier = pattern[i];
						i++;
					}
				}
				tokens.push({
					type: 2,
					name,
					modifier,
					nextLiteral: void 0
				});
				continue;
			}
			let hasEscape = false;
			const start = i;
			while (i < length) {
				const charCode = pattern.charCodeAt(i);
				if (charCode === BACKSLASH && i + 1 < length) {
					hasEscape = true;
					i += 2;
					continue;
				}
				if (charCode === OPEN_BRACKET) {
					inBrackets = true;
					i++;
					continue;
				}
				if (charCode === CLOSE_BRACKET) {
					inBrackets = false;
					i++;
					continue;
				}
				if (charCode === ASTERISK && !inBrackets) break;
				if (charCode === COLON && !inBrackets && i + 1 < length && isIdentStartCode(pattern.charCodeAt(i + 1))) break;
				i++;
			}
			if (hasEscape) {
				let value = "";
				for (let j = start; j < i; j++) {
					if (pattern.charCodeAt(j) === BACKSLASH && j + 1 < i) j++;
					value += pattern[j];
				}
				tokens.push({
					type: 0,
					value
				});
			} else tokens.push({
				type: 0,
				value: pattern.slice(start, i)
			});
		}
		let lastLiteral;
		for (let j = tokens.length - 1; j >= 0; j--) {
			const token = tokens[j];
			if (token.type === 0) lastLiteral = token.value;
			else token.nextLiteral = lastLiteral;
		}
		return tokens;
	}
	/**
	* Try to match a decoded literal against an encoded input segment.
	* Returns the number of raw input characters consumed, or -1 on failure.
	*/
	function findEncodedLiteralEnd(input, position, literal) {
		const maxLength = Math.min(input.length - position, literal.length * 3);
		for (let length = literal.length; length <= maxLength; length++) {
			const segment = input.slice(position, position + length);
			const decoded = decode$1(segment);
			if (decoded === literal) return length;
			if (decoded.length > literal.length && decoded !== segment) return -1;
		}
		return -1;
	}
	let matcherInput = "";
	let matcherInputLength = 0;
	let matcherTokens = [];
	let matcherTokenCount = 0;
	let matcherTolerateTrailingSlash = false;
	let matcherParams;
	let matcherRemainingSteps = 0;
	let matcherFailedStates;
	const matcherBoundTokens = [];
	const matcherBoundStarts = [];
	const matcherBoundEnds = [];
	function finalizeMatch() {
		const params = Object.create(null);
		let wildcardIndex = 0;
		for (let i = 0; i < matcherBoundTokens.length; i++) {
			const token = matcherBoundTokens[i];
			const start = matcherBoundStarts[i];
			const end = matcherBoundEnds[i];
			if (token.type === 1) {
				if (start !== end) params[String(wildcardIndex)] = decode$1(matcherInput.slice(start, end));
				wildcardIndex++;
				continue;
			}
			if (token.type !== 2 || start === end) continue;
			const captured = decode$1(matcherInput.slice(start, end));
			const existing = params[token.name];
			if (existing === void 0) params[token.name] = captured;
			else if (Array.isArray(existing)) existing.push(captured);
			else params[token.name] = [existing, captured];
		}
		matcherParams = params;
		return true;
	}
	function bindAndContinue(token, tokenIndex, start, end) {
		matcherBoundTokens.push(token);
		matcherBoundStarts.push(start);
		matcherBoundEnds.push(end);
		if (matchFrom(tokenIndex + 1, end)) return true;
		matcherBoundTokens.pop();
		matcherBoundStarts.pop();
		matcherBoundEnds.pop();
		return false;
	}
	function matchLiteral(token, tokenIndex, position) {
		const value = token.value;
		if (matcherInput.startsWith(value, position)) {
			if (matchFrom(tokenIndex + 1, position + value.length)) return true;
		} else if (matcherInput.indexOf("%", position) !== -1) {
			const encodedLength = findEncodedLiteralEnd(matcherInput, position, value);
			if (encodedLength !== -1 && matchFrom(tokenIndex + 1, position + encodedLength)) return true;
		}
		if (value.length > 0 && value.charCodeAt(value.length - 1) === SLASH && tokenIndex + 1 < matcherTokenCount) {
			const nextToken = matcherTokens[tokenIndex + 1];
			if (nextToken.type === 2 && (nextToken.modifier === "?" || nextToken.modifier === "*")) {
				const trimmedValue = value.slice(0, -1);
				if (matcherInput.startsWith(trimmedValue, position) && matchFrom(tokenIndex + 2, position + trimmedValue.length)) return true;
			}
		}
		return false;
	}
	function matchParamOrWildcard(token, tokenIndex, position) {
		const nextLiteralValue = token.nextLiteral;
		const isSegmentScoped = token.type === 2 && token.modifier !== "+" && token.modifier !== "*";
		const allowEmpty = token.type === 1 || token.modifier === "?" || token.modifier === "*";
		let boundary;
		if (isSegmentScoped) {
			const slashIndex = matcherInput.indexOf("/", position);
			boundary = slashIndex === -1 ? matcherInputLength : slashIndex;
		} else boundary = matcherInputLength;
		if (nextLiteralValue === void 0) {
			if (tokenIndex === matcherTokenCount - 1) {
				if (!allowEmpty && position === boundary) return false;
				if (token.type === 2 && !isSegmentScoped && matcherTolerateTrailingSlash && boundary > position && matcherInput.charCodeAt(boundary - 1) === SLASH && (allowEmpty || boundary - 1 > position) && bindAndContinue(token, tokenIndex, position, boundary - 1)) return true;
				return bindAndContinue(token, tokenIndex, position, boundary);
			}
			for (let end = position; end <= boundary; end++) {
				if (!allowEmpty && end === position) continue;
				if (bindAndContinue(token, tokenIndex, position, end)) return true;
			}
			return false;
		}
		let searchFrom = position;
		let triedEmptyCapture = false;
		while (true) {
			const occurrenceIndex = matcherInput.indexOf(nextLiteralValue, searchFrom);
			if (occurrenceIndex === -1 || occurrenceIndex > boundary) break;
			if (occurrenceIndex === position) triedEmptyCapture = true;
			if (allowEmpty || occurrenceIndex !== position) {
				if (bindAndContinue(token, tokenIndex, position, occurrenceIndex)) return true;
			}
			searchFrom = occurrenceIndex + 1;
		}
		if (allowEmpty && !triedEmptyCapture) return bindAndContinue(token, tokenIndex, position, position);
		return false;
	}
	function matchFrom(tokenIndex, position) {
		if (matcherRemainingSteps === 0) return false;
		matcherRemainingSteps--;
		if (tokenIndex === matcherTokenCount) {
			const unconsumed = matcherInputLength - position;
			if (unconsumed === 0 || matcherTolerateTrailingSlash && unconsumed === 1 && matcherInput.charCodeAt(position) === SLASH) return finalizeMatch();
			return false;
		}
		const stateKey = tokenIndex * (matcherInputLength + 1) + position;
		if (matcherFailedStates !== void 0 && matcherFailedStates.has(stateKey)) return false;
		const token = matcherTokens[tokenIndex];
		const matched = token.type === 0 ? matchLiteral(token, tokenIndex, position) : matchParamOrWildcard(token, tokenIndex, position);
		if (!matched) {
			if (matcherFailedStates === void 0) matcherFailedStates = /* @__PURE__ */ new Set();
			matcherFailedStates.add(stateKey);
		}
		return matched;
	}
	/**
	* Single linear pass that binds every wildcard/param to the same first
	* candidate the backtracking matcher would try. Returns a MatchResult
	* when it can conclude on its own, or `undefined` when it failed past
	* a point where untried alternatives exist and backtracking is needed.
	*/
	function matchTokensLinear(inputString, tokens, tolerateTrailingSlash) {
		const inputLength = inputString.length;
		const totalTokens = tokens.length;
		let position = 0;
		let wildcardIndex = 0;
		let hasAlternatives = false;
		const params = Object.create(null);
		for (let i = 0; i < totalTokens; i++) {
			const token = tokens[i];
			if (token.type === 0) {
				const value = token.value;
				let hasTrimAlternative = false;
				if (value.charCodeAt(value.length - 1) === SLASH && i + 1 < totalTokens) {
					const nextToken = tokens[i + 1];
					hasTrimAlternative = nextToken.type === 2 && (nextToken.modifier === "?" || nextToken.modifier === "*");
				}
				if (inputString.startsWith(value, position)) {
					if (hasTrimAlternative) hasAlternatives = true;
					position += value.length;
					continue;
				}
				if (inputString.indexOf("%", position) !== -1) {
					const encodedLength = findEncodedLiteralEnd(inputString, position, value);
					if (encodedLength !== -1) {
						if (hasTrimAlternative) hasAlternatives = true;
						position += encodedLength;
						continue;
					}
				}
				if (hasTrimAlternative) {
					const trimmedValue = value.slice(0, -1);
					if (inputString.startsWith(trimmedValue, position)) {
						position += trimmedValue.length;
						i++;
						continue;
					}
				}
				return hasAlternatives ? void 0 : NO_MATCH;
			}
			const nextLiteralValue = token.nextLiteral;
			const isSegmentScoped = token.type === 2 && token.modifier !== "+" && token.modifier !== "*";
			const allowEmpty = token.type === 1 || token.modifier === "?" || token.modifier === "*";
			let boundary;
			if (isSegmentScoped) {
				const slashIndex = inputString.indexOf("/", position);
				boundary = slashIndex === -1 ? inputLength : slashIndex;
			} else boundary = inputLength;
			let endPosition;
			if (nextLiteralValue === void 0) if (i === totalTokens - 1) {
				if (!allowEmpty && position === boundary) return hasAlternatives ? void 0 : NO_MATCH;
				endPosition = boundary;
				if (token.type === 2 && !isSegmentScoped && tolerateTrailingSlash && boundary > position && inputString.charCodeAt(boundary - 1) === SLASH && (allowEmpty || boundary - 1 > position)) {
					endPosition = boundary - 1;
					hasAlternatives = true;
				}
			} else {
				endPosition = allowEmpty ? position : position + 1;
				if (endPosition > boundary) return hasAlternatives ? void 0 : NO_MATCH;
				if (endPosition < boundary) hasAlternatives = true;
			}
			else {
				let occurrenceIndex = inputString.indexOf(nextLiteralValue, position);
				if (!allowEmpty && occurrenceIndex === position) occurrenceIndex = inputString.indexOf(nextLiteralValue, position + 1);
				if (occurrenceIndex === -1 || occurrenceIndex > boundary) {
					if (!allowEmpty) return hasAlternatives ? void 0 : NO_MATCH;
					endPosition = position;
				} else {
					endPosition = occurrenceIndex;
					hasAlternatives = true;
				}
			}
			if (token.type === 1) {
				if (position !== endPosition) params[String(wildcardIndex)] = decode$1(inputString.slice(position, endPosition));
				wildcardIndex++;
			} else if (position !== endPosition) {
				const captured = decode$1(inputString.slice(position, endPosition));
				const existing = params[token.name];
				if (existing === void 0) params[token.name] = captured;
				else if (Array.isArray(existing)) existing.push(captured);
				else params[token.name] = [existing, captured];
			}
			position = endPosition;
		}
		const unconsumed = inputLength - position;
		if (unconsumed !== 0 && !(tolerateTrailingSlash && unconsumed === 1 && inputString.charCodeAt(position) === SLASH)) return hasAlternatives ? void 0 : NO_MATCH;
		return {
			matches: true,
			params
		};
	}
	function matchTokens(inputString, tokens, tolerateTrailingSlash) {
		const linearResult = matchTokensLinear(inputString, tokens, tolerateTrailingSlash);
		if (linearResult !== void 0) return linearResult;
		matcherInput = inputString;
		matcherInputLength = inputString.length;
		matcherTokens = tokens;
		matcherTokenCount = tokens.length;
		matcherTolerateTrailingSlash = tolerateTrailingSlash;
		matcherParams = void 0;
		matcherRemainingSteps = MAX_MATCH_STEPS;
		matcherFailedStates = void 0;
		matcherBoundTokens.length = 0;
		matcherBoundStarts.length = 0;
		matcherBoundEnds.length = 0;
		matchFrom(0, 0);
		if (matcherParams === void 0) return NO_MATCH;
		return {
			matches: true,
			params: matcherParams
		};
	}
	function removeQueryAndFragment(input) {
		const hashIndex = input.indexOf("#");
		if (hashIndex !== -1) input = input.slice(0, hashIndex);
		const queryIndex = input.indexOf("?");
		return queryIndex === -1 ? input : input.slice(0, queryIndex);
	}
	function removeTrailingSlash(input) {
		if (input.length > 1 && input.charCodeAt(input.length - 1) === SLASH) return input.slice(0, -1);
		return input;
	}
	function decode$1(value) {
		if (value.indexOf("%") === -1) return value;
		try {
			return decodeURIComponent(value);
		} catch {
			return value;
		}
	}
	/**
	* Match a URL against the given pattern.
	* @example
	* matchPattern('http://localhost/user/:userId', 'http://localhost/user/123')
	* // { matches: true, params: { userId: '123' } }
	*/
	function matchPattern(pattern, input) {
		const rawInput = typeof input === "string" ? input : input.href;
		if (rawInput.length > MAX_INPUT_LENGTH) throw new Error(`matchPattern: input URL exceeds the maximum allowed length of ${MAX_INPUT_LENGTH} characters (received ${rawInput.length}).`);
		const inputString = lowercaseSchemeAndHost(removeQueryAndFragment(rawInput));
		const { tokens, isLiteralOnly, hasTrailingSlash, normalizedPattern } = parsePatternOrGetFromCache(pattern);
		if (isLiteralOnly) {
			if (inputString === normalizedPattern || decode$1(inputString) === normalizedPattern) return {
				matches: true,
				params: Object.create(null)
			};
			if (!hasTrailingSlash) {
				const stripped = removeTrailingSlash(inputString);
				if (stripped === normalizedPattern || decode$1(stripped) === normalizedPattern) return {
					matches: true,
					params: Object.create(null)
				};
			}
			return NO_MATCH;
		}
		return matchTokens(inputString, tokens, !hasTrailingSlash);
	}
	//#endregion
	//#region src/utils/get-clean-url-string.ts
	const REDUNDANT_CHARACTERS_EXP = /[?|#].*$/g;
	/**
	* Removes search parameters and the fragment from a given URL string.
	* Unlike `getCleanUrl()` from Interceptors, accepts relative URLs and
	* path patterns (e.g. "/user/:id?") since it never parses the input as a URL.
	*/
	function getCleanUrlString(url) {
		if (url.endsWith("?")) return url;
		return url.replace(REDUNDANT_CHARACTERS_EXP, "");
	}
	//#endregion
	//#region src/core/utils/url/is-absolute-url.ts
	/**
	* Determines if the given URL string is an absolute URL.
	*/
	function isAbsoluteUrl(url) {
		return /^([a-z][a-z\d+\-.]*:)?\/\//i.test(url);
	}
	//#endregion
	//#region src/core/utils/url/get-absolute-url.ts
	/**
	* Returns an absolute URL based on the given path.
	*/
	function getAbsoluteUrl(path, baseUrl) {
		if (isAbsoluteUrl(path)) return path;
		if (path.startsWith("*")) return path;
		const origin = baseUrl || typeof location !== "undefined" && location.href;
		return origin ? decodeURI(new URL(encodeURI(path), origin).href) : path;
	}
	//#endregion
	//#region src/core/utils/matching/normalize-path.ts
	/**
	* Normalizes a given request handler path:
	* - Preserves RegExp.
	* - Removes query parameters and hashes.
	* - Rebases relative URLs against the "baseUrl" or the current location.
	* - Preserves relative URLs in Node.js, unless specified otherwise.
	* - Preserves optional path parameters.
	*/
	function normalizePath(path, baseUrl) {
		if (path instanceof RegExp) return path;
		return getCleanUrlString(getAbsoluteUrl(path, baseUrl));
	}
	//#endregion
	//#region src/core/utils/matching/match-request-url.ts
	function isPath(value) {
		return typeof value === "string" || value instanceof RegExp;
	}
	/**
	* Match the given URL against a path pattern.
	*/
	function matchRequestUrl(url, pattern, baseUrl) {
		const cleanUrl = getCleanUrl(url);
		if (pattern instanceof RegExp) {
			const match = pattern.flags.includes("g") ? [...cleanUrl.matchAll(pattern)].flat() : cleanUrl.match(pattern);
			return {
				matches: match != null && match.length > 0,
				params: Object.fromEntries((match ?? []).slice(1).map((value, index) => [index, value]))
			};
		}
		return matchPattern(normalizePath(pattern, baseUrl), cleanUrl);
	}
	//#endregion
	//#region src/core/utils/request/to-public-url.ts
	/**
	* Returns a relative URL if the given request URL is relative
	* to the current origin. Otherwise returns an absolute URL.
	*/
	function toPublicUrl(url) {
		const urlInstance = url instanceof URL ? url : new URL(url);
		if (typeof location !== "undefined" && urlInstance.origin === location.origin) return urlInstance.pathname;
		return urlInstance.origin + urlInstance.pathname;
	}
	//#endregion
	//#region node_modules/.pnpm/cookie@2.0.1/node_modules/cookie/dist/index.js
	const NullObject = /* @__PURE__ */ (() => {
		const C = function() {};
		C.prototype = Object.create(null);
		return C;
	})();
	/**
	* Parse a `Cookie` header.
	*
	* Parse the given cookie header string into an object
	* The object has the various cookies as keys(names) => values
	*/
	function parseCookie(str, options) {
		const obj = new NullObject();
		const len = str.length;
		if (len < 2) return obj;
		const dec = options?.decode || decode;
		let index = 0;
		do {
			const eqIdx = eqIndex(str, index, len);
			if (eqIdx === len) break;
			const endIdx = endIndex(str, index, len);
			if (eqIdx > endIdx) {
				index = str.lastIndexOf(";", eqIdx - 1) + 1;
				continue;
			}
			const key = valueSlice(str, index, eqIdx);
			if (obj[key] === void 0) obj[key] = dec(valueSlice(str, eqIdx + 1, endIdx));
			index = endIdx + 1;
		} while (index < len);
		return obj;
	}
	/**
	* Find the next `;` character, or return `len`.
	*/
	function endIndex(str, min, len) {
		const index = str.indexOf(";", min);
		return index === -1 ? len : index;
	}
	/**
	* Find the next `=` character, or return `len`.
	*/
	function eqIndex(str, min, len) {
		const index = str.indexOf("=", min);
		return index === -1 ? len : index;
	}
	/**
	* Slice out a value between startPod to max.
	*/
	function valueSlice(str, min, max) {
		if (min === max) return "";
		let start = min;
		let end = max;
		do {
			const code = str.charCodeAt(start);
			if (code !== 32 && code !== 9) break;
		} while (++start < end);
		while (end > start) {
			const code = str.charCodeAt(end - 1);
			if (code !== 32 && code !== 9) break;
			end--;
		}
		return str.slice(start, end);
	}
	/**
	* URL-decode string value. Optimized to skip native call when no %.
	*/
	function decode(str) {
		if (str.indexOf("%") === -1) return str;
		try {
			return decodeURIComponent(str);
		} catch (e) {
			return str;
		}
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/domain.js
	/**
	* Check if `vhost` is a valid suffix of `hostname` (top-domain)
	*
	* It means that `vhost` needs to be a suffix of `hostname` and we then need to
	* make sure that: either they are equal, or the character preceding `vhost` in
	* `hostname` is a '.' (it should not be a partial label).
	*
	* * hostname = 'not.evil.com' and vhost = 'vil.com'      => not ok
	* * hostname = 'not.evil.com' and vhost = 'evil.com'     => ok
	* * hostname = 'not.evil.com' and vhost = 'not.evil.com' => ok
	*/
	function shareSameDomainSuffix(hostname, vhost) {
		if (hostname.endsWith(vhost)) return hostname.length === vhost.length || hostname[hostname.length - vhost.length - 1] === ".";
		return false;
	}
	/**
	* Given a hostname and its public suffix, extract the general domain.
	*/
	function extractDomainWithSuffix(hostname, publicSuffix) {
		const publicSuffixIndex = hostname.length - publicSuffix.length - 2;
		const lastDotBeforeSuffixIndex = hostname.lastIndexOf(".", publicSuffixIndex);
		if (lastDotBeforeSuffixIndex === -1) return hostname;
		return hostname.slice(lastDotBeforeSuffixIndex + 1);
	}
	/**
	* Detects the domain based on rules and upon and a host string
	*/
	function getDomain$1(suffix, hostname, options) {
		if (options.validHosts !== null) {
			const validHosts = options.validHosts;
			for (const vhost of validHosts) if (shareSameDomainSuffix(hostname, vhost)) return vhost;
		}
		let numberOfLeadingDots = 0;
		if (hostname.startsWith(".")) while (numberOfLeadingDots < hostname.length && hostname[numberOfLeadingDots] === ".") numberOfLeadingDots += 1;
		if (suffix.length === hostname.length - numberOfLeadingDots) return null;
		return extractDomainWithSuffix(hostname, suffix);
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/domain-without-suffix.js
	/**
	* Return the part of domain without suffix.
	*
	* Example: for domain 'foo.com', the result would be 'foo'.
	*/
	function getDomainWithoutSuffix(domain, suffix) {
		return domain.slice(0, -suffix.length - 1);
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/extract-hostname.js
	/**
	* Matches an ASCII tab (U+0009) or newline (U+000A / U+000D). The WHATWG URL
	* parser strips these before parsing; we only allocate a cleaned copy (and
	* re-parse) on the rare input that actually contains one.
	*/
	const CONTROL_CHARS$1 = /[\t\n\r]/g;
	let extractedHostnameValidated = false;
	/**
	* True if char `code` is a valid hostname character. This is the per-char half
	* of `is-valid.ts`'s `isValidAscii` (a-z, 0-9, > U+007F) PLUS three additions:
	* A-Z (the host is lowercased before validation, so uppercase ≡ a valid
	* lowercase letter) and '-' / '_' (valid inside a label). KEEP IN SYNC with
	* `is-valid.ts`: these rules are deliberately duplicated to validate during
	* extraction, so any change to the accepted character set there must be
	* mirrored here (and vice-versa).
	*/
	function isValidHostnameChar(code) {
		return code >= 97 && code <= 122 || code >= 48 && code <= 57 || code > 127 || code >= 65 && code <= 90 || code === 45 || code === 95;
	}
	/**
	* Classify scheme `url.slice(schemeStart, colonIndex)` as a WHATWG special
	* scheme without allocating a substring (case-insensitive via `| 32`).
	* Special schemes: ftp, file, http, https, ws, wss
	* (https://url.spec.whatwg.org/#special-scheme).
	*
	* @returns 0 = not special, 1 = special, 2 = file (its host sits only between
	*          "//" and the next slash).
	*/
	function getSpecialScheme(url, schemeStart, colonIndex) {
		const length = colonIndex - schemeStart;
		const c0 = url.charCodeAt(schemeStart) | 32;
		if (length === 2) return c0 === 119 && (url.charCodeAt(schemeStart + 1) | 32) === 115 ? 1 : 0;
		else if (length === 3) {
			const c1 = url.charCodeAt(schemeStart + 1) | 32;
			const c2 = url.charCodeAt(schemeStart + 2) | 32;
			if (c0 === 119 && c1 === 115 && c2 === 115) return 1;
			if (c0 === 102 && c1 === 116 && c2 === 112) return 1;
			return 0;
		} else if (length === 4) {
			const c1 = url.charCodeAt(schemeStart + 1) | 32;
			const c2 = url.charCodeAt(schemeStart + 2) | 32;
			const c3 = url.charCodeAt(schemeStart + 3) | 32;
			if (c0 === 104 && c1 === 116 && c2 === 116 && c3 === 112) return 1;
			if (c0 === 102 && c1 === 105 && c2 === 108 && c3 === 101) return 2;
			return 0;
		} else if (length === 5) return c0 === 104 && (url.charCodeAt(schemeStart + 1) | 32) === 116 && (url.charCodeAt(schemeStart + 2) | 32) === 116 && (url.charCodeAt(schemeStart + 3) | 32) === 112 && (url.charCodeAt(schemeStart + 4) | 32) === 115 ? 1 : 0;
		return 0;
	}
	/**
	* Extract a hostname from `url`, matching a WHATWG URL parser's host-boundary
	* behaviour (https://url.spec.whatwg.org/#concept-basic-url-parser) for tldts'
	* scope. It deliberately does NOT normalise the host (no IDNA/punycode or IPv4
	* canonicalisation; IPv6 brackets are stripped, not compressed), strips trailing
	* dots, and stays lenient where a strict parser rejects (bare host:port,
	* out-of-range port, user@host) — all documented deviations.
	*
	* @param urlIsValidHostname - when true, `url` is already a valid hostname and is
	*   returned by the same reference (factory.ts skips re-validation on that
	*   identity), keeping the common path allocation-free.
	* @param validate - when true, validate the host inline during the authority
	*   scan and publish the verdict via `extractedHostnameValidated` so `parseImpl`
	*   can skip the redundant `isValidHostname` pass for simple authorities.
	*/
	function extractHostname(url, urlIsValidHostname, validate = false) {
		let start = 0;
		let end = url.length;
		let hasUpper = false;
		let isSpecial = false;
		extractedHostnameValidated = false;
		if (!urlIsValidHostname) {
			if (url.startsWith("data:")) return null;
			while (start < url.length && url.charCodeAt(start) <= 32) start += 1;
			while (end > start + 1 && url.charCodeAt(end - 1) <= 32) end -= 1;
			if (url.charCodeAt(start) === 47 && url.charCodeAt(start + 1) === 47) start += 2;
			else {
				const indexOfProtocol = url.indexOf(":/", start);
				if (indexOfProtocol !== -1) {
					const special = getSpecialScheme(url, start, indexOfProtocol);
					if (special === 1) {
						isSpecial = true;
						start = indexOfProtocol + 2;
						while (url.charCodeAt(start) === 47 || url.charCodeAt(start) === 92) start += 1;
					} else if (special === 2) {
						isSpecial = true;
						start = indexOfProtocol + 1;
						let slashes = 0;
						while ((url.charCodeAt(start) === 47 || url.charCodeAt(start) === 92) && slashes < 2) {
							start += 1;
							slashes += 1;
						}
						if (slashes < 2) return null;
					} else {
						for (let i = start; i < indexOfProtocol; i += 1) {
							const code = url.charCodeAt(i) | 32;
							if (!(code >= 97 && code <= 122 || code >= 48 && code <= 57 || code === 46 || code === 45 || code === 43)) {
								const raw = url.charCodeAt(i);
								if (raw === 9 || raw === 10 || raw === 13) return extractHostname(url.replace(CONTROL_CHARS$1, ""), urlIsValidHostname, validate);
								return null;
							}
						}
						if (url.charCodeAt(indexOfProtocol + 2) === 47) start = indexOfProtocol + 3;
						else return null;
					}
				} else if (url.charCodeAt(start) !== 91) {
					let indexOfColon = -1;
					for (let i = start; i < end; i += 1) {
						const code = url.charCodeAt(i);
						if (code === 9 || code === 10 || code === 13) return extractHostname(url.replace(CONTROL_CHARS$1, ""), urlIsValidHostname, validate);
						if (code === 58) {
							indexOfColon = i;
							break;
						}
						if (code === 47 || code === 92 || code === 63 || code === 35) break;
					}
					if (indexOfColon !== -1) {
						let hasIdentifier = false;
						for (let i = indexOfColon + 1; i < end; i += 1) {
							const code = url.charCodeAt(i);
							if (code === 47 || code === 92 || code === 63 || code === 35) break;
							if (code === 64) {
								hasIdentifier = true;
								break;
							}
						}
						if (!hasIdentifier) {
							let allDigits = true;
							let i = indexOfColon + 1;
							for (; i < end; i += 1) {
								const code = url.charCodeAt(i);
								if (code === 47 || code === 92 || code === 63 || code === 35) break;
								if (code < 48 || code > 57) {
									allDigits = false;
									break;
								}
							}
							if (i === indexOfColon + 1) allDigits = false;
							if (!allDigits) {
								const special = getSpecialScheme(url, start, indexOfColon);
								if (special === 0) {
									let isBareIpv6 = false;
									for (let j = indexOfColon + 1; j < end; j += 1) {
										const code = url.charCodeAt(j);
										if (code === 47 || code === 92 || code === 63 || code === 35) break;
										if (code === 58) {
											isBareIpv6 = true;
											break;
										}
									}
									if (!isBareIpv6) return null;
								} else {
									isSpecial = true;
									start = indexOfColon + 1;
									if (special === 2) {
										let slashes = 0;
										while ((url.charCodeAt(start) === 47 || url.charCodeAt(start) === 92) && slashes < 2) {
											start += 1;
											slashes += 1;
										}
										if (slashes < 2) return null;
									} else while (url.charCodeAt(start) === 47 || url.charCodeAt(start) === 92) start += 1;
								}
							}
						}
					}
				}
			}
			let indexOfIdentifier = -1;
			let indexOfClosingBracket = -1;
			let indexOfPort = -1;
			let indexOfFirstColon = -1;
			let hasControl = false;
			let vValid = validate;
			let vLastDot = start - 1;
			let vLastCode = -1;
			if (validate && start < end) {
				const c0 = url.charCodeAt(start);
				if (!(isValidHostnameChar(c0) || c0 === 46 || c0 === 95) || c0 === 45) vValid = false;
			}
			for (let i = start; i < end; i += 1) {
				const code = url.charCodeAt(i);
				if (code < 64) {
					if (code === 47 || code === 35 || code === 63) {
						end = i;
						break;
					} else if (code === 58) {
						if (indexOfFirstColon === -1) indexOfFirstColon = i;
						indexOfPort = i;
					} else if (code === 9 || code === 10 || code === 13) hasControl = true;
					else if (validate) {
						if (code === 46) {
							if (i - vLastDot > 64 || vLastCode === 46 || vLastCode === 45) vValid = false;
							vLastDot = i;
						} else if (code < 48 || code > 57) {
							if (code !== 45 || vLastCode === 46) vValid = false;
						}
					}
				} else if (isSpecial && code === 92) {
					end = i;
					break;
				} else if (code === 64) {
					indexOfIdentifier = i;
					indexOfFirstColon = -1;
				} else if (code === 93) indexOfClosingBracket = i;
				else if (code >= 65 && code <= 90) hasUpper = true;
				else if (validate && !isValidHostnameChar(code)) vValid = false;
				if (validate) vLastCode = code;
			}
			if (hasControl) return extractHostname(url.replace(CONTROL_CHARS$1, ""), urlIsValidHostname, validate);
			if (indexOfIdentifier !== -1 && indexOfIdentifier >= start && indexOfIdentifier < end) start = indexOfIdentifier + 1;
			if (url.charCodeAt(start) === 91) {
				if (indexOfClosingBracket !== -1) return url.slice(start + 1, indexOfClosingBracket).toLowerCase();
				return null;
			} else if (indexOfPort !== -1 && indexOfPort > start && indexOfPort < end && indexOfFirstColon === indexOfPort) end = indexOfPort;
			if (start >= end) return null;
			if (validate && vValid && indexOfIdentifier === -1 && indexOfPort === -1 && indexOfClosingBracket === -1 && url.charCodeAt(end - 1) !== 46 && end - start <= 255 && end - vLastDot - 1 <= 63 && vLastCode !== 45) extractedHostnameValidated = true;
		}
		while (end > start + 1 && url.charCodeAt(end - 1) === 46) end -= 1;
		const hostname = start !== 0 || end !== url.length ? url.slice(start, end) : url;
		if (hasUpper) return hostname.toLowerCase();
		return hostname;
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/is-ip.js
	/**
	* Check if a hostname is an IP. You should be aware that this only works
	* because `hostname` is already garanteed to be a valid hostname!
	*/
	function isProbablyIpv4(hostname) {
		if (hostname.length < 7) return false;
		if (hostname.length > 15) return false;
		let numberOfDots = 0;
		for (let i = 0; i < hostname.length; i += 1) {
			const code = hostname.charCodeAt(i);
			if (code === 46) numberOfDots += 1;
			else if (code < 48 || code > 57) return false;
		}
		return numberOfDots === 3 && hostname.charCodeAt(0) !== 46 && hostname.charCodeAt(hostname.length - 1) !== 46;
	}
	/**
	* Similar to isProbablyIpv4.
	*/
	function isProbablyIpv6(hostname) {
		if (hostname.length < 3) return false;
		let start = hostname.startsWith("[") ? 1 : 0;
		let end = hostname.length;
		if (hostname[end - 1] === "]") end -= 1;
		if (end - start > 39) return false;
		let hasColon = false;
		for (; start < end; start += 1) {
			const code = hostname.charCodeAt(start);
			if (code === 58) hasColon = true;
			else if (!(code >= 48 && code <= 57 || code >= 97 && code <= 102 || code >= 65 && code <= 70)) return false;
		}
		return hasColon;
	}
	/**
	* Check if `hostname` is *probably* a valid ip addr (either ipv6 or ipv4).
	* This *will not* work on any string. We need `hostname` to be a valid
	* hostname.
	*/
	function isIp(hostname) {
		return isProbablyIpv6(hostname) || isProbablyIpv4(hostname);
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/is-special-use.js
	/**
	* Special-use domain names from the IANA "Special-Use Domain Names" registry:
	* the authoritative list, created by RFC 6761 and maintained as new RFCs add to
	* it: https://www.iana.org/assignments/special-use-domain-names/
	* Snapshot: 2026-05-24. (RFC 6761 is not obsoleted; draft-hoffman-rfc6761bis
	* proposes to retire its prose but keep this registry, so the registry is the
	* source of truth; re-sync this list against it.)
	*
	* These names never correspond to a public registration, yet neither
	* `isIcann` nor `isPrivate` marks one as special-use: most are absent from the
	* Public Suffix List (so `a.test` looks like a registrable domain), and the
	* few that are listed (`onion`, `home.arpa`) appear there as ordinary ICANN
	* suffixes. `isSpecialUse` is the single signal that covers them all.
	*
	* Per the registry and RFC 6761 ("and any names falling within these domains"),
	* the designation covers each listed name AND all of its sub-domains. DNS labels
	* are case-insensitive (RFC 4343); `hostname` is expected to be already
	* lower-cased and trailing-dot-stripped, as produced by `extractHostname`, the
	* same normalization the Public-Suffix-List lookup relies on.
	*
	* Two groups of registry entries are intentionally excluded: the numeric
	* reverse-DNS delegation zones (`10.in-addr.arpa`, the `*.ip6.arpa` ranges, …),
	* which are reverse-DNS PTR zones rather than hostnames and whose parents
	* (`in-addr.arpa`/`ip6.arpa`) are already in the Public Suffix List; and the
	* deprecated `eap-noob.arpa` entry.
	*/
	const SPECIAL_USE_DOMAINS$1 = [
		"test",
		"localhost",
		"invalid",
		"example",
		"example.com",
		"example.net",
		"example.org",
		"local",
		"onion",
		"alt",
		"home.arpa",
		"ipv4only.arpa",
		"resolver.arpa",
		"service.arpa",
		"6tisch.arpa",
		"eap.arpa"
	];
	/**
	* Return `true` if `hostname` is, or is a sub-domain of, a special-use domain
	* (see the registry note above). Expects an already-normalized `hostname`.
	*/
	function isSpecialUse(hostname) {
		for (const name of SPECIAL_USE_DOMAINS$1) if (hostname.endsWith(name) && (hostname.length === name.length || hostname.charCodeAt(hostname.length - name.length - 1) === 46)) return true;
		return false;
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/is-valid.js
	/**
	* Implements fast shallow verification of hostnames. This does not perform a
	* struct check on the content of labels (classes of Unicode characters, etc.)
	* but instead check that the structure is valid (number of labels, length of
	* labels, etc.).
	*
	* If you need stricter validation, consider using an external library.
	*/
	function isValidAscii(code) {
		return code >= 97 && code <= 122 || code >= 48 && code <= 57 || code > 127;
	}
	/**
	* Check if a hostname string is valid. It's usually a preliminary check before
	* trying to use getDomain or anything else.
	*
	* Beware: it does not check if the TLD exists.
	*/
	function is_valid_default(hostname) {
		if (hostname.length > 255) return false;
		if (hostname.length === 0) return false;
		if (!isValidAscii(hostname.charCodeAt(0)) && hostname.charCodeAt(0) !== 46 && hostname.charCodeAt(0) !== 95) return false;
		let lastDotIndex = -1;
		let lastCharCode = -1;
		const len = hostname.length;
		for (let i = 0; i < len; i += 1) {
			const code = hostname.charCodeAt(i);
			if (code === 46) {
				if (i - lastDotIndex > 64 || lastCharCode === 46 || lastCharCode === 45) return false;
				lastDotIndex = i;
			} else if (!(isValidAscii(code) || code === 45 || code === 95) || code === 45 && lastCharCode === 46) return false;
			lastCharCode = code;
		}
		return len - lastDotIndex - 1 <= 63 && lastCharCode !== 45;
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/options.js
	function setDefaultsImpl({ allowIcannDomains = true, allowPrivateDomains = false, detectIp = true, detectSpecialUse = false, extractHostname = true, mixedInputs = true, validHosts = null, validateHostname = true }) {
		return {
			allowIcannDomains,
			allowPrivateDomains,
			detectIp,
			detectSpecialUse,
			extractHostname,
			mixedInputs,
			validHosts,
			validateHostname
		};
	}
	const DEFAULT_OPTIONS = setDefaultsImpl({});
	function setDefaults(options) {
		if (options === void 0) return DEFAULT_OPTIONS;
		return setDefaultsImpl(options);
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/subdomain.js
	/**
	* Returns the subdomain of a hostname string
	*/
	function getSubdomain(hostname, domain) {
		if (domain.length === hostname.length) return "";
		return hostname.slice(0, -domain.length - 1);
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/factory.js
	/**
	* Implement a factory allowing to plug different implementations of suffix
	* lookup (e.g.: using a trie or the packed hashes datastructures). This is used
	* and exposed in `tldts.ts` and `tldts-experimental.ts` bundle entrypoints.
	*/
	function getEmptyResult() {
		return {
			domain: null,
			domainWithoutSuffix: null,
			hostname: null,
			isIcann: null,
			isIp: null,
			isPrivate: null,
			isSpecialUse: null,
			publicSuffix: null,
			subdomain: null
		};
	}
	function resetResult(result) {
		result.domain = null;
		result.domainWithoutSuffix = null;
		result.hostname = null;
		result.isIcann = null;
		result.isIp = null;
		result.isPrivate = null;
		result.isSpecialUse = null;
		result.publicSuffix = null;
		result.subdomain = null;
	}
	function parseImpl$1(url, step, suffixLookup, partialOptions, result) {
		const options = setDefaults(partialOptions);
		if (typeof url !== "string") return result;
		let urlIsValid = false;
		if (!options.extractHostname) result.hostname = url;
		else if (options.mixedInputs) {
			urlIsValid = is_valid_default(url);
			result.hostname = extractHostname(url, urlIsValid, options.validateHostname);
		} else result.hostname = extractHostname(url, false, options.validateHostname);
		if (options.detectIp && result.hostname !== null) {
			result.isIp = isIp(result.hostname);
			if (result.isIp) return result;
		}
		if (options.validateHostname && options.extractHostname && result.hostname !== null && !(urlIsValid && result.hostname === url) && !extractedHostnameValidated && !is_valid_default(result.hostname)) {
			result.hostname = null;
			return result;
		}
		if (step === 0 || result.hostname === null) return result;
		if (step === 5 && options.detectSpecialUse) result.isSpecialUse = isSpecialUse(result.hostname);
		suffixLookup(result.hostname, options, result);
		if (step === 2 || result.publicSuffix === null) return result;
		result.domain = getDomain$1(result.publicSuffix, result.hostname, options);
		if (step === 3 || result.domain === null) return result;
		result.subdomain = getSubdomain(result.hostname, result.domain);
		if (step === 4) return result;
		result.domainWithoutSuffix = getDomainWithoutSuffix(result.domain, result.publicSuffix);
		return result;
	}
	//#endregion
	//#region node_modules/.pnpm/tldts-core@7.4.15/node_modules/tldts-core/dist/es6/src/lookup/fast-path.js
	function fast_path_default(hostname, options, out) {
		if (!options.allowPrivateDomains && hostname.length > 3) {
			const last = hostname.length - 1;
			const c3 = hostname.charCodeAt(last);
			const c2 = hostname.charCodeAt(last - 1);
			const c1 = hostname.charCodeAt(last - 2);
			const c0 = hostname.charCodeAt(last - 3);
			if (c3 === 109 && c2 === 111 && c1 === 99 && c0 === 46) {
				out.isIcann = true;
				out.isPrivate = false;
				out.publicSuffix = "com";
				return true;
			} else if (c3 === 103 && c2 === 114 && c1 === 111 && c0 === 46) {
				out.isIcann = true;
				out.isPrivate = false;
				out.publicSuffix = "org";
				return true;
			} else if (c3 === 117 && c2 === 100 && c1 === 101 && c0 === 46) {
				out.isIcann = true;
				out.isPrivate = false;
				out.publicSuffix = "edu";
				return true;
			} else if (c3 === 118 && c2 === 111 && c1 === 103 && c0 === 46) {
				out.isIcann = true;
				out.isPrivate = false;
				out.publicSuffix = "gov";
				return true;
			} else if (c3 === 116 && c2 === 101 && c1 === 110 && c0 === 46) {
				out.isIcann = true;
				out.isPrivate = false;
				out.publicSuffix = "net";
				return true;
			} else if (c3 === 101 && c2 === 100 && c1 === 46) {
				out.isIcann = true;
				out.isPrivate = false;
				out.publicSuffix = "de";
				return true;
			}
		}
		return false;
	}
	//#endregion
	//#region node_modules/.pnpm/tldts@7.4.15/node_modules/tldts/dist/es6/src/data/trie.js
	const nodeFlags = /*#__PURE__*/ new Uint8Array([
		1,
		2,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		2,
		2,
		2,
		0,
		2,
		2,
		0,
		2,
		0,
		0,
		1,
		0,
		0,
		2,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		0,
		1,
		1,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		2,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		2,
		0,
		2,
		2,
		0,
		0,
		2,
		2,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		1,
		0,
		2,
		1,
		1,
		2,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		2,
		0,
		0,
		0,
		0,
		0,
		0,
		2,
		2,
		0,
		0,
		0,
		0,
		0,
		2,
		0,
		0,
		0,
		2,
		0,
		0,
		0,
		0,
		0,
		0,
		2,
		0,
		2,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		2,
		0,
		0,
		0,
		0,
		2,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		2,
		2,
		0,
		0,
		0,
		2,
		0,
		1,
		1,
		0,
		2,
		0,
		2,
		2,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		2,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		2,
		2,
		0,
		2,
		2,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		0,
		2,
		2,
		0,
		2,
		2,
		2,
		2,
		0,
		0,
		0,
		0,
		2,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		2,
		2,
		0,
		0,
		0,
		2,
		2,
		1,
		1,
		1,
		1,
		1,
		2,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		2,
		2,
		0,
		0,
		2,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		2,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		2,
		2,
		1,
		2,
		1,
		1,
		1,
		2,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		2,
		1,
		1,
		1,
		1,
		2,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		2,
		1,
		1,
		1,
		1,
		2,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0
	]);
	const edgeStart = /*#__PURE__*/ new Uint16Array([
		0,
		0,
		0,
		10,
		11,
		18,
		106,
		111,
		117,
		124,
		130,
		136,
		145,
		146,
		147,
		148,
		149,
		150,
		151,
		153,
		154,
		155,
		157,
		159,
		226,
		239,
		241,
		242,
		243,
		258,
		265,
		266,
		269,
		270,
		271,
		274,
		276,
		295,
		296,
		298,
		307,
		312,
		329,
		330,
		333,
		335,
		336,
		338,
		372,
		373,
		375,
		378,
		379,
		383,
		385,
		389,
		392,
		424,
		427,
		440,
		441,
		449,
		450,
		452,
		462,
		476,
		477,
		478,
		487,
		488,
		525,
		530,
		546,
		566,
		572,
		614,
		615,
		642,
		669,
		670,
		818,
		824,
		827,
		828,
		829,
		834,
		839,
		848,
		870,
		871,
		872,
		873,
		874,
		875,
		876,
		894,
		896,
		897,
		900,
		902,
		903,
		905,
		907,
		922,
		937,
		942,
		943,
		945,
		946,
		947,
		948,
		949,
		951,
		954,
		959,
		960,
		961,
		963,
		964,
		967,
		970,
		971,
		972,
		985,
		987,
		999,
		1010,
		1018,
		1020,
		1061,
		1064,
		1068,
		1069,
		1071,
		1074,
		1085,
		1087,
		1097,
		1099,
		1105,
		1107,
		1108,
		1110,
		1113,
		1114,
		1115,
		1168,
		1170,
		1172,
		1192,
		1193,
		1194,
		1195,
		1197,
		1208,
		1239,
		1250,
		1262,
		1271,
		1278,
		1283,
		1296,
		1307,
		1320,
		1321,
		1332,
		1366,
		1367,
		1368,
		1383,
		1398,
		1470,
		1471,
		1473,
		1474,
		1508,
		1509,
		1510,
		1511,
		1514,
		1518,
		1521,
		1523,
		1552,
		1553,
		1561,
		1562,
		1563,
		1564,
		1566,
		1568,
		1569,
		1571,
		1572,
		1573,
		1584,
		1585,
		1586,
		1587,
		1588,
		1589,
		1590,
		1591,
		1592,
		1593,
		1594,
		1595,
		1596,
		1597,
		1599,
		1600,
		1601,
		2055,
		2058,
		2059,
		2061,
		2068,
		2075,
		2085,
		2089,
		2100,
		2101,
		2102,
		2114,
		2115,
		2117,
		2119,
		2120,
		2127,
		2128,
		2130,
		2131,
		2133,
		2134,
		2135,
		2136,
		2137,
		2211,
		2213,
		2234,
		2235,
		2236,
		2238,
		2264,
		2265,
		2316,
		2317,
		2319,
		2326,
		2332,
		2342,
		2352,
		2405,
		2406,
		2407,
		2417,
		2431,
		2432,
		2435,
		2442,
		2443,
		2451,
		2452,
		2453,
		2454,
		2455,
		2466,
		2467,
		2468,
		2470,
		2471,
		2472,
		2481,
		2493,
		2499,
		2531,
		2535,
		2537,
		2538,
		2540,
		2541,
		2552,
		2553,
		2555,
		2563,
		2570,
		2576,
		2581,
		2582,
		2588,
		2591,
		2597,
		2604,
		2605,
		2612,
		2620,
		2621,
		2622,
		2660,
		2666,
		2681,
		2682,
		2687,
		2705,
		2736,
		2754,
		2756,
		2759,
		2767,
		2769,
		2776,
		2828,
		2852,
		2853,
		2854,
		2855,
		2856,
		2857,
		2858,
		2865,
		2866,
		2867,
		2868,
		2869,
		2870,
		2872,
		2873,
		2877,
		2957,
		2970,
		2971,
		3408,
		3412,
		3426,
		3478,
		3506,
		3528,
		3586,
		3608,
		3623,
		3686,
		3737,
		3775,
		3811,
		3836,
		3978,
		4024,
		4075,
		4094,
		4128,
		4143,
		4163,
		4193,
		4224,
		4247,
		4278,
		4308,
		4340,
		4367,
		4442,
		4464,
		4502,
		4512,
		4546,
		4565,
		4591,
		4633,
		4683,
		4709,
		4778,
		4779,
		4781,
		4804,
		4827,
		4863,
		4894,
		4911,
		4968,
		4981,
		5005,
		5034,
		5036,
		5070,
		5086,
		5114,
		5419,
		5428,
		5437,
		5444,
		5461,
		5465,
		5471,
		5510,
		5512,
		5519,
		5526,
		5535,
		5542,
		5543,
		5544,
		5556,
		5559,
		5574,
		5575,
		5584,
		5585,
		5594,
		5603,
		5609,
		5611,
		5612,
		5613,
		5650,
		5651,
		5653,
		5661,
		5668,
		5681,
		5685,
		5687,
		5688,
		5694,
		5701,
		5715,
		5725,
		5730,
		5738,
		5746,
		5752,
		5753,
		5757,
		5759,
		5760,
		5772,
		5844,
		5845,
		5846,
		5847,
		5849,
		5850,
		5853,
		5855,
		5858,
		5862,
		5863,
		5864,
		5870,
		5871,
		5872,
		5874,
		5876,
		5878,
		5879,
		5880,
		5883,
		5885,
		5888,
		5889,
		5891,
		6089,
		6096,
		6097,
		6098,
		6108,
		6113,
		6130,
		6144,
		6153,
		6154,
		6155,
		6159,
		6160,
		6162,
		6164,
		6170,
		6171,
		6174,
		6175,
		6177,
		6178,
		6179,
		7079,
		7082,
		7086,
		7104,
		7113,
		7116,
		7123,
		7124,
		7126,
		7127,
		7128,
		7130,
		7182,
		7183,
		7186,
		7187,
		7304,
		7305,
		7316,
		7327,
		7334,
		7337,
		7346,
		7347,
		7348,
		7363,
		7418,
		7609,
		7611,
		7612,
		7614,
		7619,
		7632,
		7647,
		7654,
		7663,
		7666,
		7669,
		7676,
		7684,
		7688,
		7689,
		7690,
		7704,
		7708,
		7717,
		7718,
		7719,
		7723,
		7758,
		7759,
		7777,
		7784,
		7792,
		7793,
		7798,
		7806,
		7850,
		7851,
		7857,
		7860,
		7872,
		7877,
		7878,
		7881,
		7883,
		7918,
		7919,
		7925,
		7932,
		7933,
		7942,
		7951,
		7966,
		7970,
		7971,
		8023,
		8024,
		8029,
		8031,
		8034,
		8036,
		8037,
		8038,
		8047,
		8061,
		8069,
		8083,
		8095,
		8096,
		8098,
		8100,
		8122,
		8133,
		8139,
		8140,
		8152,
		8164,
		8251,
		8263,
		8271,
		8274,
		8280,
		8305,
		8308,
		8309,
		8310,
		8311,
		8313,
		8316,
		8319,
		8330,
		8332,
		8334,
		8362,
		8437,
		8444,
		8448,
		8449,
		8458,
		8480,
		8481,
		8486,
		8487,
		8566,
		8568,
		8570,
		8579,
		8583,
		8589,
		8595,
		8601,
		8611,
		8616,
		8617,
		8635,
		8646,
		8651,
		8656,
		8666,
		8672,
		8676,
		8682,
		8688,
		10297,
		10298,
		10299,
		10306,
		10308
	]);
	const edgeLength = /*#__PURE__*/ new Uint8Array([
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		8,
		8,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		8,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		5,
		5,
		9,
		12,
		19,
		8,
		19,
		8,
		11,
		9,
		9,
		8,
		7,
		7,
		6,
		8,
		9,
		16,
		10,
		7,
		7,
		11,
		8,
		6,
		6,
		9,
		7,
		11,
		7,
		14,
		4,
		4,
		4,
		4,
		4,
		4,
		10,
		7,
		6,
		6,
		6,
		6,
		10,
		10,
		6,
		10,
		10,
		22,
		11,
		9,
		10,
		10,
		10,
		9,
		10,
		8,
		7,
		7,
		7,
		8,
		21,
		13,
		11,
		11,
		9,
		10,
		9,
		13,
		10,
		8,
		8,
		9,
		12,
		9,
		7,
		10,
		7,
		7,
		13,
		7,
		3,
		3,
		3,
		3,
		3,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		8,
		6,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		5,
		3,
		3,
		3,
		7,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		1,
		1,
		7,
		8,
		5,
		2,
		2,
		7,
		2,
		2,
		1,
		4,
		1,
		11,
		9,
		9,
		5,
		5,
		8,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		5,
		11,
		9,
		9,
		13,
		7,
		14,
		7,
		6,
		6,
		6,
		7,
		6,
		6,
		6,
		6,
		6,
		10,
		7,
		11,
		9,
		4,
		4,
		4,
		4,
		4,
		6,
		6,
		6,
		6,
		13,
		6,
		8,
		7,
		10,
		9,
		9,
		9,
		8,
		9,
		8,
		7,
		10,
		6,
		9,
		8,
		10,
		10,
		7,
		8,
		1,
		9,
		10,
		12,
		12,
		12,
		10,
		9,
		9,
		10,
		10,
		9,
		9,
		1,
		1,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		6,
		6,
		4,
		3,
		3,
		3,
		7,
		4,
		4,
		4,
		3,
		3,
		6,
		7,
		3,
		4,
		1,
		2,
		2,
		2,
		6,
		1,
		2,
		2,
		2,
		2,
		2,
		12,
		5,
		3,
		8,
		9,
		13,
		4,
		4,
		13,
		9,
		9,
		11,
		7,
		3,
		12,
		9,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		8,
		2,
		2,
		3,
		3,
		3,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		3,
		7,
		10,
		15,
		7,
		15,
		15,
		20,
		15,
		9,
		10,
		10,
		12,
		14,
		14,
		14,
		12,
		12,
		12,
		12,
		12,
		14,
		14,
		10,
		10,
		10,
		10,
		14,
		9,
		9,
		9,
		10,
		14,
		14,
		14,
		13,
		13,
		9,
		9,
		9,
		9,
		9,
		9,
		7,
		8,
		6,
		8,
		8,
		6,
		8,
		13,
		8,
		8,
		6,
		13,
		8,
		11,
		13,
		8,
		6,
		13,
		8,
		6,
		9,
		10,
		10,
		12,
		14,
		14,
		14,
		12,
		12,
		12,
		12,
		14,
		14,
		10,
		10,
		10,
		10,
		9,
		9,
		9,
		10,
		14,
		14,
		11,
		13,
		13,
		9,
		9,
		9,
		9,
		9,
		9,
		2,
		6,
		9,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		7,
		7,
		2,
		3,
		2,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		5,
		7,
		2,
		2,
		12,
		8,
		10,
		8,
		10,
		7,
		18,
		4,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		5,
		2,
		2,
		3,
		3,
		3,
		5,
		5,
		3,
		8,
		8,
		6,
		8,
		6,
		6,
		4,
		6,
		7,
		7,
		7,
		10,
		11,
		2,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		6,
		11,
		10,
		7,
		7,
		7,
		4,
		4,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		2,
		2,
		7,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		7,
		7,
		7,
		11,
		7,
		6,
		9,
		6,
		6,
		8,
		10,
		8,
		6,
		8,
		13,
		4,
		4,
		4,
		4,
		4,
		10,
		8,
		11,
		8,
		8,
		8,
		10,
		10,
		7,
		10,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		1,
		1,
		2,
		2,
		2,
		2,
		2,
		2,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		7,
		10,
		13,
		7,
		8,
		7,
		11,
		8,
		8,
		6,
		9,
		8,
		8,
		6,
		6,
		6,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		9,
		7,
		6,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		6,
		6,
		9,
		7,
		8,
		10,
		8,
		8,
		2,
		3,
		3,
		3,
		3,
		3,
		2,
		8,
		9,
		9,
		2,
		2,
		2,
		3,
		3,
		3,
		2,
		3,
		3,
		3,
		9,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		12,
		5,
		5,
		3,
		5,
		4,
		2,
		3,
		2,
		4,
		3,
		9,
		2,
		2,
		2,
		2,
		2,
		5,
		5,
		3,
		8,
		8,
		13,
		6,
		10,
		9,
		4,
		7,
		9,
		11,
		2,
		3,
		7,
		3,
		3,
		4,
		1,
		3,
		4,
		2,
		9,
		3,
		3,
		12,
		5,
		3,
		7,
		10,
		10,
		7,
		4,
		4,
		6,
		14,
		7,
		9,
		7,
		13,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		8,
		15,
		4,
		4,
		2,
		3,
		3,
		3,
		7,
		4,
		9,
		9,
		2,
		3,
		3,
		3,
		5,
		3,
		2,
		2,
		7,
		2,
		7,
		6,
		6,
		7,
		2,
		4,
		2,
		2,
		2,
		2,
		2,
		2,
		8,
		8,
		8,
		9,
		5,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		10,
		7,
		4,
		4,
		4,
		4,
		3,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		10,
		7,
		4,
		4,
		4,
		4,
		2,
		3,
		3,
		3,
		3,
		10,
		7,
		4,
		4,
		4,
		4,
		3,
		9,
		6,
		6,
		6,
		9,
		13,
		9,
		2,
		2,
		2,
		8,
		7,
		9,
		5,
		3,
		3,
		3,
		5,
		5,
		13,
		12,
		9,
		10,
		7,
		8,
		7,
		6,
		8,
		6,
		11,
		12,
		7,
		9,
		10,
		4,
		4,
		7,
		8,
		11,
		6,
		7,
		9,
		8,
		7,
		10,
		8,
		9,
		15,
		7,
		8,
		5,
		4,
		7,
		2,
		3,
		3,
		3,
		2,
		14,
		10,
		2,
		14,
		10,
		2,
		14,
		3,
		9,
		13,
		13,
		10,
		14,
		16,
		17,
		11,
		2,
		14,
		2,
		14,
		3,
		9,
		13,
		10,
		14,
		16,
		17,
		11,
		14,
		10,
		14,
		2,
		7,
		3,
		10,
		7,
		14,
		10,
		2,
		14,
		10,
		9,
		9,
		17,
		6,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		10,
		10,
		10,
		12,
		9,
		4,
		10,
		10,
		11,
		8,
		8,
		8,
		7,
		9,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		8,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		16,
		3,
		3,
		14,
		3,
		14,
		2,
		14,
		9,
		13,
		10,
		10,
		14,
		16,
		17,
		11,
		6,
		9,
		10,
		10,
		12,
		14,
		14,
		14,
		12,
		12,
		12,
		12,
		14,
		14,
		10,
		10,
		10,
		10,
		14,
		9,
		9,
		9,
		10,
		14,
		14,
		14,
		9,
		9,
		9,
		9,
		9,
		9,
		2,
		14,
		9,
		13,
		10,
		10,
		14,
		16,
		17,
		11,
		6,
		2,
		14,
		9,
		17,
		13,
		10,
		10,
		14,
		16,
		17,
		11,
		6,
		2,
		14,
		9,
		13,
		10,
		14,
		16,
		17,
		11,
		2,
		14,
		9,
		13,
		10,
		16,
		11,
		2,
		14,
		10,
		19,
		7,
		2,
		14,
		9,
		13,
		10,
		19,
		10,
		7,
		14,
		16,
		17,
		11,
		6,
		2,
		14,
		9,
		13,
		10,
		19,
		7,
		14,
		16,
		17,
		11,
		2,
		14,
		9,
		13,
		17,
		13,
		10,
		10,
		14,
		16,
		17,
		11,
		6,
		3,
		2,
		14,
		9,
		13,
		10,
		10,
		14,
		16,
		17,
		11,
		6,
		9,
		10,
		12,
		14,
		14,
		14,
		12,
		12,
		12,
		12,
		12,
		14,
		14,
		14,
		10,
		10,
		10,
		14,
		9,
		9,
		9,
		9,
		14,
		14,
		14,
		13,
		13,
		14,
		9,
		9,
		9,
		9,
		9,
		9,
		4,
		11,
		2,
		14,
		9,
		13,
		17,
		13,
		10,
		19,
		10,
		7,
		14,
		16,
		17,
		11,
		6,
		2,
		14,
		9,
		13,
		17,
		13,
		10,
		19,
		10,
		7,
		14,
		16,
		17,
		11,
		6,
		2,
		9,
		10,
		10,
		7,
		17,
		3,
		3,
		12,
		12,
		16,
		15,
		15,
		12,
		14,
		14,
		14,
		20,
		20,
		13,
		12,
		12,
		12,
		12,
		12,
		12,
		20,
		25,
		14,
		14,
		12,
		12,
		10,
		10,
		10,
		10,
		9,
		9,
		9,
		25,
		4,
		9,
		17,
		10,
		7,
		14,
		16,
		21,
		13,
		13,
		14,
		20,
		14,
		13,
		17,
		24,
		9,
		12,
		13,
		25,
		13,
		21,
		20,
		17,
		9,
		9,
		9,
		9,
		9,
		9,
		12,
		17,
		4,
		4,
		9,
		9,
		9,
		10,
		10,
		12,
		14,
		14,
		14,
		12,
		12,
		12,
		12,
		12,
		14,
		14,
		10,
		10,
		10,
		10,
		14,
		9,
		9,
		9,
		10,
		14,
		14,
		14,
		13,
		13,
		9,
		9,
		9,
		9,
		9,
		9,
		1,
		5,
		8,
		7,
		11,
		11,
		1,
		3,
		3,
		3,
		5,
		3,
		3,
		4,
		8,
		9,
		10,
		14,
		14,
		12,
		12,
		12,
		12,
		14,
		14,
		10,
		10,
		10,
		10,
		14,
		9,
		9,
		9,
		10,
		14,
		14,
		14,
		13,
		13,
		9,
		9,
		9,
		9,
		9,
		7,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		7,
		4,
		9,
		12,
		6,
		14,
		4,
		12,
		7,
		2,
		2,
		1,
		2,
		7,
		6,
		4,
		4,
		4,
		6,
		8,
		8,
		7,
		4,
		5,
		6,
		3,
		3,
		3,
		3,
		4,
		16,
		8,
		5,
		4,
		3,
		3,
		3,
		5,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		11,
		12,
		7,
		7,
		13,
		9,
		10,
		17,
		12,
		8,
		9,
		7,
		8,
		5,
		12,
		10,
		13,
		14,
		5,
		5,
		5,
		13,
		5,
		5,
		5,
		3,
		3,
		3,
		5,
		16,
		5,
		5,
		5,
		5,
		7,
		12,
		14,
		8,
		12,
		8,
		10,
		12,
		9,
		11,
		7,
		9,
		7,
		10,
		7,
		13,
		9,
		7,
		12,
		8,
		17,
		7,
		7,
		16,
		10,
		13,
		13,
		8,
		10,
		10,
		14,
		17,
		7,
		16,
		16,
		15,
		8,
		10,
		10,
		12,
		17,
		17,
		7,
		17,
		14,
		7,
		10,
		17,
		8,
		7,
		7,
		7,
		8,
		15,
		15,
		7,
		14,
		10,
		10,
		10,
		11,
		11,
		7,
		7,
		13,
		8,
		10,
		7,
		16,
		7,
		8,
		7,
		14,
		17,
		12,
		10,
		11,
		21,
		8,
		9,
		7,
		13,
		9,
		8,
		13,
		6,
		12,
		7,
		6,
		13,
		10,
		10,
		10,
		8,
		18,
		9,
		17,
		13,
		10,
		12,
		6,
		13,
		6,
		11,
		8,
		13,
		10,
		13,
		18,
		13,
		11,
		13,
		8,
		16,
		7,
		10,
		8,
		16,
		12,
		10,
		8,
		8,
		14,
		11,
		8,
		15,
		8,
		8,
		7,
		7,
		12,
		7,
		8,
		9,
		14,
		15,
		8,
		9,
		10,
		9,
		15,
		7,
		8,
		8,
		12,
		13,
		9,
		10,
		15,
		13,
		7,
		10,
		10,
		20,
		7,
		6,
		9,
		6,
		6,
		14,
		11,
		14,
		11,
		12,
		9,
		10,
		16,
		16,
		12,
		7,
		11,
		28,
		8,
		11,
		10,
		7,
		21,
		8,
		7,
		9,
		4,
		4,
		4,
		17,
		7,
		8,
		6,
		9,
		6,
		6,
		13,
		6,
		6,
		6,
		6,
		18,
		20,
		14,
		8,
		11,
		12,
		9,
		10,
		13,
		15,
		15,
		19,
		8,
		9,
		12,
		7,
		10,
		16,
		12,
		9,
		9,
		9,
		14,
		12,
		11,
		9,
		12,
		11,
		18,
		9,
		9,
		9,
		10,
		7,
		7,
		16,
		8,
		9,
		7,
		13,
		12,
		10,
		14,
		18,
		7,
		8,
		11,
		7,
		7,
		8,
		8,
		13,
		7,
		7,
		7,
		11,
		15,
		13,
		11,
		7,
		8,
		15,
		11,
		7,
		8,
		18,
		14,
		13,
		18,
		15,
		10,
		12,
		12,
		9,
		7,
		11,
		11,
		8,
		7,
		10,
		8,
		14,
		12,
		10,
		18,
		7,
		10,
		9,
		7,
		8,
		13,
		10,
		14,
		10,
		8,
		8,
		23,
		7,
		7,
		11,
		12,
		12,
		17,
		7,
		7,
		11,
		11,
		17,
		16,
		16,
		7,
		8,
		11,
		14,
		14,
		8,
		10,
		7,
		7,
		16,
		16,
		13,
		9,
		11,
		9,
		15,
		15,
		11,
		11,
		7,
		7,
		14,
		7,
		9,
		7,
		7,
		16,
		10,
		13,
		10,
		11,
		14,
		7,
		11,
		10,
		11,
		7,
		11,
		10,
		11,
		15,
		11,
		15,
		10,
		12,
		10,
		14,
		13,
		11,
		11,
		12,
		13,
		10,
		7,
		13,
		10,
		16,
		12,
		21,
		9,
		10,
		10,
		7,
		11,
		14,
		17,
		7,
		7,
		8,
		11,
		12,
		8,
		15,
		14,
		14,
		8,
		17,
		12,
		10,
		10,
		7,
		9,
		11,
		7,
		10,
		7,
		11,
		18,
		7,
		11,
		7,
		12,
		11,
		8,
		8,
		14,
		12,
		7,
		8,
		15,
		3,
		7,
		7,
		5,
		2,
		9,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		11,
		6,
		4,
		7,
		10,
		7,
		7,
		11,
		1,
		10,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		7,
		3,
		5,
		6,
		3,
		3,
		5,
		2,
		2,
		5,
		3,
		4,
		13,
		11,
		3,
		3,
		6,
		3,
		5,
		14,
		2,
		2,
		3,
		8,
		2,
		2,
		12,
		5,
		18,
		5,
		3,
		3,
		3,
		16,
		5,
		5,
		5,
		10,
		7,
		13,
		12,
		13,
		9,
		12,
		14,
		19,
		9,
		9,
		21,
		9,
		9,
		10,
		6,
		9,
		6,
		15,
		10,
		6,
		12,
		8,
		6,
		10,
		15,
		4,
		4,
		6,
		6,
		9,
		9,
		12,
		16,
		14,
		23,
		7,
		7,
		7,
		14,
		9,
		7,
		7,
		11,
		14,
		10,
		7,
		10,
		10,
		10,
		12,
		6,
		11,
		10,
		13,
		11,
		15,
		11,
		7,
		12,
		10,
		3,
		7,
		1,
		1,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		4,
		3,
		7,
		2,
		5,
		5,
		3,
		3,
		5,
		5,
		5,
		5,
		7,
		6,
		6,
		6,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		6,
		6,
		6,
		6,
		7,
		10,
		2,
		2,
		2,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		10,
		9,
		11,
		8,
		7,
		12,
		8,
		9,
		7,
		6,
		13,
		11,
		6,
		13,
		7,
		9,
		9,
		4,
		4,
		4,
		4,
		4,
		6,
		10,
		7,
		8,
		13,
		8,
		8,
		9,
		14,
		7,
		8,
		10,
		7,
		7,
		7,
		9,
		6,
		9,
		7,
		2,
		12,
		5,
		3,
		3,
		13,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		8,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		9,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		2,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		1,
		7,
		6,
		4,
		12,
		3,
		3,
		3,
		3,
		3,
		8,
		7,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		11,
		14,
		2,
		8,
		3,
		5,
		5,
		8,
		10,
		8,
		6,
		4,
		7,
		17,
		7,
		4,
		5,
		2,
		6,
		3,
		2,
		2,
		12,
		5,
		5,
		3,
		15,
		13,
		8,
		11,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		5,
		3,
		3,
		3,
		3,
		4,
		18,
		2,
		12,
		5,
		3,
		3,
		3,
		3,
		3,
		5,
		16,
		8,
		8,
		9,
		6,
		6,
		4,
		4,
		4,
		4,
		31,
		6,
		6,
		10,
		11,
		21,
		10,
		9,
		7,
		10,
		7,
		7,
		2,
		4,
		4,
		4,
		4,
		6,
		5,
		3,
		3,
		4,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		6,
		6,
		2,
		2,
		2,
		5,
		3,
		3,
		3,
		7,
		7,
		4,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		3,
		3,
		3,
		3,
		8,
		2,
		3,
		3,
		3,
		3,
		3,
		5,
		9,
		11,
		3,
		3,
		3,
		3,
		4,
		4,
		3,
		3,
		3,
		3,
		3,
		5,
		10,
		9,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		2,
		3,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		11,
		10,
		10,
		10,
		10,
		10,
		11,
		10,
		11,
		10,
		11,
		10,
		9,
		9,
		11,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		3,
		7,
		8,
		8,
		7,
		6,
		6,
		11,
		4,
		4,
		4,
		7,
		8,
		9,
		9,
		2,
		3,
		7,
		4,
		4,
		2,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		4,
		4,
		4,
		4,
		2,
		2,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		5,
		5,
		5,
		7,
		7,
		6,
		6,
		6,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		6,
		8,
		8,
		1,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		6,
		9,
		12,
		3,
		7,
		10,
		7,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		4,
		3,
		3,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		8,
		8,
		6,
		6,
		8,
		6,
		7,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		7,
		5,
		5,
		20,
		19,
		8,
		10,
		9,
		7,
		10,
		6,
		8,
		11,
		6,
		6,
		6,
		6,
		13,
		12,
		8,
		6,
		7,
		14,
		11,
		9,
		2,
		5,
		3,
		6,
		2,
		3,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		5,
		4,
		3,
		7,
		6,
		4,
		7,
		4,
		3,
		6,
		4,
		7,
		2,
		7,
		7,
		7,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		9,
		10,
		10,
		11,
		7,
		8,
		20,
		7,
		8,
		9,
		8,
		12,
		6,
		6,
		6,
		8,
		9,
		8,
		12,
		6,
		6,
		8,
		13,
		10,
		12,
		6,
		6,
		7,
		7,
		9,
		6,
		4,
		4,
		4,
		4,
		4,
		4,
		10,
		6,
		6,
		6,
		7,
		14,
		11,
		10,
		7,
		8,
		10,
		8,
		11,
		14,
		11,
		11,
		9,
		7,
		9,
		8,
		11,
		9,
		17,
		10,
		9,
		2,
		2,
		2,
		9,
		3,
		3,
		3,
		3,
		15,
		14,
		9,
		5,
		5,
		2,
		8,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		15,
		12,
		22,
		19,
		17,
		18,
		18,
		19,
		21,
		7,
		16,
		16,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		9,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		7,
		16,
		11,
		11,
		7,
		7,
		7,
		7,
		17,
		7,
		8,
		12,
		15,
		9,
		19,
		7,
		19,
		8,
		21,
		11,
		12,
		19,
		14,
		22,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		16,
		16,
		19,
		24,
		12,
		7,
		14,
		7,
		12,
		7,
		8,
		10,
		10,
		13,
		7,
		12,
		12,
		7,
		7,
		10,
		18,
		15,
		12,
		16,
		7,
		14,
		12,
		17,
		10,
		16,
		17,
		12,
		17,
		25,
		7,
		7,
		7,
		13,
		6,
		9,
		6,
		9,
		18,
		6,
		6,
		11,
		20,
		10,
		6,
		6,
		6,
		6,
		6,
		6,
		17,
		6,
		6,
		6,
		15,
		6,
		6,
		6,
		6,
		6,
		8,
		14,
		11,
		12,
		11,
		15,
		13,
		19,
		17,
		21,
		7,
		18,
		8,
		13,
		13,
		8,
		12,
		8,
		6,
		6,
		13,
		6,
		15,
		15,
		16,
		6,
		6,
		16,
		6,
		6,
		6,
		14,
		6,
		18,
		6,
		6,
		6,
		17,
		18,
		9,
		13,
		15,
		8,
		19,
		8,
		15,
		15,
		18,
		14,
		16,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		11,
		10,
		11,
		6,
		21,
		23,
		12,
		17,
		12,
		11,
		14,
		13,
		22,
		15,
		15,
		11,
		12,
		14,
		12,
		7,
		12,
		8,
		12,
		14,
		12,
		18,
		10,
		8,
		16,
		19,
		17,
		12,
		14,
		15,
		8,
		19,
		17,
		12,
		13,
		13,
		15,
		18,
		13,
		23,
		24,
		23,
		21,
		17,
		24,
		8,
		21,
		8,
		14,
		14,
		16,
		20,
		14,
		8,
		8,
		15,
		20,
		8,
		19,
		21,
		9,
		8,
		13,
		12,
		13,
		15,
		11,
		8,
		11,
		9,
		9,
		8,
		11,
		8,
		21,
		14,
		21,
		15,
		15,
		13,
		7,
		19,
		7,
		7,
		7,
		7,
		7,
		7,
		16,
		12,
		17,
		18,
		7,
		7,
		11,
		11,
		7,
		9,
		9,
		2,
		2,
		3,
		3,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		10,
		10,
		7,
		9,
		7,
		7,
		7,
		6,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		7,
		6,
		8,
		6,
		6,
		9,
		7,
		7,
		7,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		8,
		9,
		8,
		7,
		8,
		7,
		8,
		10,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		9,
		7,
		7,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		6,
		6,
		9,
		11,
		13,
		7,
		8,
		9,
		9,
		5,
		5,
		5,
		7,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		7,
		8,
		9,
		7,
		10,
		9,
		10,
		7,
		8,
		5,
		5,
		5,
		5,
		5,
		5,
		7,
		7,
		9,
		8,
		7,
		7,
		6,
		6,
		6,
		6,
		6,
		6,
		10,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		10,
		4,
		4,
		4,
		4,
		8,
		7,
		7,
		10,
		10,
		9,
		8,
		8,
		15,
		9,
		8,
		8,
		8,
		8,
		8,
		9,
		10,
		9,
		10,
		7,
		8,
		13,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		7,
		8,
		6,
		6,
		6,
		4,
		4,
		11,
		9,
		7,
		8,
		9,
		10,
		7,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		6,
		6,
		13,
		7,
		9,
		8,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		7,
		8,
		7,
		8,
		13,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		8,
		8,
		6,
		6,
		6,
		6,
		7,
		6,
		7,
		6,
		6,
		9,
		7,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		7,
		8,
		7,
		8,
		9,
		8,
		8,
		8,
		7,
		10,
		7,
		8,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		7,
		7,
		7,
		7,
		9,
		7,
		10,
		9,
		6,
		6,
		6,
		6,
		6,
		8,
		8,
		6,
		6,
		6,
		7,
		6,
		6,
		6,
		9,
		9,
		4,
		4,
		13,
		7,
		10,
		9,
		9,
		12,
		7,
		8,
		8,
		10,
		8,
		8,
		8,
		8,
		8,
		8,
		5,
		5,
		5,
		5,
		3,
		7,
		7,
		11,
		7,
		9,
		8,
		8,
		6,
		6,
		10,
		6,
		8,
		8,
		8,
		6,
		7,
		6,
		6,
		12,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		9,
		8,
		8,
		16,
		8,
		9,
		8,
		7,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		7,
		7,
		10,
		15,
		8,
		9,
		8,
		9,
		9,
		6,
		6,
		6,
		6,
		6,
		6,
		7,
		4,
		8,
		7,
		8,
		8,
		7,
		8,
		11,
		8,
		5,
		5,
		5,
		5,
		5,
		3,
		7,
		7,
		6,
		11,
		16,
		7,
		6,
		4,
		4,
		4,
		4,
		9,
		9,
		8,
		8,
		8,
		13,
		12,
		8,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		11,
		7,
		8,
		8,
		9,
		13,
		7,
		7,
		7,
		9,
		8,
		8,
		9,
		12,
		7,
		12,
		7,
		12,
		8,
		7,
		10,
		12,
		9,
		9,
		6,
		6,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		8,
		9,
		11,
		8,
		6,
		6,
		6,
		6,
		6,
		12,
		7,
		6,
		6,
		6,
		9,
		7,
		7,
		6,
		6,
		6,
		6,
		6,
		11,
		9,
		6,
		6,
		6,
		6,
		6,
		7,
		9,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		9,
		9,
		9,
		9,
		7,
		7,
		7,
		7,
		7,
		11,
		7,
		7,
		8,
		8,
		8,
		8,
		8,
		8,
		9,
		8,
		9,
		9,
		7,
		7,
		11,
		11,
		7,
		12,
		8,
		8,
		8,
		8,
		8,
		7,
		8,
		8,
		8,
		8,
		8,
		13,
		12,
		8,
		8,
		8,
		8,
		7,
		7,
		7,
		9,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		7,
		11,
		7,
		8,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		10,
		11,
		6,
		7,
		9,
		4,
		4,
		4,
		4,
		4,
		4,
		9,
		9,
		8,
		9,
		8,
		8,
		8,
		7,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		11,
		7,
		7,
		7,
		9,
		6,
		6,
		11,
		8,
		10,
		6,
		6,
		6,
		12,
		8,
		8,
		7,
		6,
		6,
		8,
		7,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		9,
		10,
		9,
		9,
		8,
		10,
		9,
		11,
		8,
		5,
		5,
		5,
		7,
		6,
		6,
		8,
		7,
		4,
		4,
		4,
		4,
		8,
		7,
		7,
		8,
		7,
		8,
		8,
		5,
		5,
		5,
		5,
		7,
		7,
		8,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		10,
		8,
		9,
		13,
		6,
		7,
		6,
		6,
		8,
		7,
		8,
		4,
		4,
		4,
		4,
		11,
		8,
		8,
		8,
		10,
		5,
		5,
		8,
		7,
		8,
		13,
		8,
		7,
		6,
		8,
		6,
		9,
		7,
		8,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		8,
		9,
		6,
		4,
		8,
		10,
		10,
		8,
		12,
		9,
		13,
		2,
		7,
		5,
		5,
		5,
		5,
		5,
		7,
		7,
		10,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		8,
		4,
		4,
		9,
		8,
		8,
		8,
		14,
		8,
		8,
		8,
		9,
		8,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		9,
		6,
		6,
		6,
		6,
		10,
		12,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		4,
		4,
		4,
		4,
		11,
		8,
		7,
		8,
		8,
		8,
		5,
		5,
		3,
		3,
		3,
		3,
		7,
		7,
		6,
		8,
		6,
		8,
		11,
		7,
		6,
		6,
		6,
		7,
		4,
		8,
		11,
		9,
		10,
		5,
		5,
		5,
		3,
		3,
		3,
		7,
		7,
		8,
		9,
		8,
		15,
		9,
		6,
		6,
		6,
		6,
		6,
		6,
		11,
		11,
		4,
		4,
		4,
		4,
		4,
		7,
		9,
		9,
		10,
		8,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		7,
		4,
		4,
		4,
		4,
		4,
		9,
		9,
		8,
		8,
		10,
		13,
		5,
		5,
		5,
		3,
		17,
		7,
		7,
		7,
		7,
		7,
		8,
		6,
		8,
		13,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		4,
		4,
		4,
		9,
		10,
		8,
		8,
		8,
		5,
		5,
		5,
		5,
		3,
		7,
		7,
		7,
		8,
		8,
		6,
		6,
		6,
		8,
		8,
		8,
		9,
		10,
		8,
		4,
		8,
		10,
		9,
		8,
		8,
		8,
		9,
		13,
		10,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		8,
		9,
		9,
		7,
		7,
		7,
		10,
		9,
		9,
		8,
		9,
		8,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		8,
		12,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		12,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		11,
		8,
		8,
		9,
		9,
		10,
		8,
		9,
		7,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		7,
		8,
		7,
		6,
		6,
		8,
		6,
		6,
		10,
		4,
		7,
		8,
		9,
		12,
		8,
		7,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		14,
		7,
		9,
		8,
		8,
		6,
		6,
		8,
		12,
		12,
		6,
		6,
		7,
		7,
		10,
		4,
		4,
		4,
		4,
		4,
		9,
		9,
		14,
		9,
		13,
		8,
		7,
		5,
		5,
		5,
		6,
		6,
		6,
		7,
		4,
		8,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		7,
		7,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		12,
		6,
		6,
		6,
		6,
		4,
		4,
		9,
		9,
		8,
		8,
		11,
		7,
		7,
		7,
		5,
		5,
		5,
		3,
		9,
		8,
		6,
		6,
		7,
		4,
		4,
		4,
		4,
		4,
		4,
		8,
		8,
		11,
		5,
		5,
		5,
		7,
		7,
		7,
		9,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		8,
		4,
		4,
		4,
		4,
		7,
		12,
		9,
		8,
		8,
		8,
		7,
		10,
		10,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		11,
		14,
		8,
		7,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		8,
		7,
		6,
		6,
		6,
		7,
		6,
		8,
		9,
		4,
		4,
		4,
		7,
		8,
		9,
		7,
		9,
		7,
		7,
		9,
		8,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		11,
		3,
		9,
		7,
		7,
		12,
		14,
		8,
		6,
		6,
		12,
		11,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		15,
		7,
		4,
		4,
		4,
		16,
		9,
		9,
		9,
		8,
		9,
		9,
		9,
		9,
		9,
		8,
		8,
		8,
		13,
		11,
		8,
		5,
		5,
		5,
		5,
		3,
		7,
		6,
		6,
		8,
		8,
		8,
		6,
		6,
		7,
		10,
		7,
		4,
		4,
		4,
		4,
		9,
		7,
		8,
		7,
		7,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		7,
		7,
		7,
		9,
		6,
		6,
		6,
		6,
		6,
		8,
		8,
		7,
		7,
		9,
		6,
		6,
		6,
		7,
		6,
		6,
		6,
		6,
		6,
		15,
		4,
		4,
		4,
		4,
		4,
		8,
		8,
		7,
		8,
		12,
		9,
		8,
		8,
		8,
		8,
		8,
		9,
		8,
		8,
		10,
		8,
		8,
		8,
		8,
		16,
		9,
		10,
		2,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		9,
		7,
		6,
		8,
		9,
		4,
		4,
		4,
		4,
		4,
		7,
		8,
		8,
		8,
		9,
		8,
		11,
		10,
		5,
		5,
		5,
		5,
		3,
		7,
		8,
		6,
		6,
		6,
		6,
		6,
		8,
		6,
		6,
		6,
		6,
		4,
		12,
		10,
		12,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		5,
		5,
		5,
		5,
		3,
		3,
		7,
		7,
		10,
		8,
		9,
		7,
		6,
		10,
		7,
		6,
		6,
		4,
		4,
		8,
		9,
		7,
		9,
		9,
		9,
		9,
		8,
		8,
		8,
		8,
		10,
		5,
		5,
		5,
		5,
		5,
		5,
		8,
		7,
		6,
		6,
		6,
		10,
		6,
		7,
		10,
		7,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		12,
		9,
		10,
		7,
		7,
		10,
		8,
		10,
		5,
		12,
		9,
		6,
		6,
		6,
		6,
		6,
		7,
		6,
		4,
		4,
		4,
		10,
		9,
		9,
		8,
		7,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		13,
		7,
		7,
		9,
		7,
		7,
		7,
		8,
		9,
		9,
		7,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		7,
		13,
		9,
		15,
		15,
		4,
		4,
		4,
		4,
		4,
		10,
		10,
		9,
		8,
		9,
		8,
		8,
		9,
		7,
		8,
		7,
		8,
		5,
		5,
		7,
		6,
		6,
		6,
		4,
		4,
		4,
		7,
		8,
		11,
		8,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		7,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		11,
		10,
		7,
		4,
		4,
		4,
		9,
		8,
		8,
		5,
		5,
		5,
		5,
		5,
		9,
		9,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		9,
		4,
		4,
		4,
		4,
		8,
		8,
		8,
		9,
		9,
		8,
		8,
		8,
		13,
		2,
		4,
		2,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		9,
		9,
		6,
		6,
		6,
		6,
		10,
		8,
		8,
		8,
		6,
		6,
		6,
		4,
		4,
		9,
		8,
		10,
		8,
		9,
		8,
		8,
		8,
		9,
		8,
		8,
		5,
		3,
		3,
		3,
		11,
		6,
		6,
		6,
		7,
		6,
		6,
		6,
		4,
		4,
		9,
		8,
		5,
		5,
		5,
		5,
		5,
		3,
		11,
		8,
		6,
		6,
		6,
		6,
		6,
		9,
		7,
		4,
		4,
		14,
		10,
		9,
		8,
		12,
		8,
		8,
		8,
		11,
		15,
		8,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		11,
		11,
		11,
		10,
		10,
		7,
		7,
		3,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		7,
		11,
		7,
		7,
		11,
		11,
		7,
		8,
		9,
		10,
		7,
		7,
		9,
		9,
		9,
		9,
		7,
		7,
		10,
		8,
		13,
		8,
		8,
		8,
		8,
		11,
		10,
		6,
		6,
		8,
		10,
		11,
		14,
		14,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		11,
		7,
		7,
		6,
		8,
		12,
		11,
		11,
		6,
		6,
		10,
		6,
		6,
		6,
		6,
		6,
		10,
		7,
		7,
		6,
		6,
		11,
		6,
		6,
		6,
		11,
		8,
		9,
		7,
		6,
		10,
		11,
		9,
		10,
		11,
		7,
		11,
		8,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		8,
		6,
		6,
		8,
		9,
		10,
		9,
		6,
		6,
		6,
		10,
		6,
		6,
		6,
		6,
		11,
		10,
		11,
		10,
		9,
		8,
		7,
		7,
		7,
		7,
		11,
		14,
		8,
		10,
		9,
		9,
		8,
		8,
		7,
		11,
		8,
		8,
		8,
		11,
		11,
		10,
		10,
		9,
		10,
		8,
		11,
		10,
		8,
		11,
		9,
		12,
		8,
		10,
		8,
		11,
		8,
		9,
		9,
		11,
		11,
		10,
		11,
		13,
		8,
		7,
		8,
		8,
		9,
		7,
		8,
		8,
		8,
		8,
		7,
		8,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		4,
		4,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		8,
		6,
		4,
		4,
		4,
		11,
		7,
		11,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		8,
		7,
		7,
		8,
		8,
		4,
		8,
		7,
		7,
		7,
		9,
		7,
		8,
		9,
		8,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		5,
		5,
		3,
		3,
		8,
		8,
		6,
		9,
		4,
		4,
		10,
		7,
		3,
		3,
		3,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		3,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		4,
		10,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		2,
		3,
		3,
		3,
		5,
		2,
		4,
		2,
		6,
		2,
		2,
		9,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		5,
		9,
		8,
		7,
		9,
		6,
		6,
		11,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		6,
		7,
		7,
		11,
		8,
		8,
		6,
		5,
		11,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		4,
		4,
		4,
		4,
		3,
		3,
		3,
		3,
		5,
		7,
		2,
		3,
		3,
		3,
		3,
		3,
		8,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		4,
		4,
		4,
		4,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		3,
		3,
		3,
		3,
		3,
		6,
		3,
		3,
		8,
		10,
		3,
		4,
		4,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		8,
		9,
		10,
		7,
		7,
		1,
		14,
		18,
		13,
		18,
		13,
		10,
		10,
		16,
		13,
		18,
		16,
		13,
		16,
		18,
		13,
		22,
		16,
		16,
		16,
		14,
		21,
		16,
		9,
		14,
		16,
		9,
		9,
		14,
		10,
		10,
		14,
		12,
		14,
		19,
		12,
		11,
		18,
		13,
		17,
		15,
		15,
		15,
		15,
		16,
		14,
		13,
		19,
		18,
		15,
		19,
		18,
		12,
		18,
		12,
		11,
		20,
		14,
		15,
		10,
		17,
		17,
		16,
		19,
		20,
		21,
		15,
		13,
		16,
		15,
		15,
		15,
		1,
		1,
		3,
		8,
		7,
		7,
		8,
		8,
		8,
		1,
		6,
		1,
		1,
		6,
		3,
		3,
		4,
		7,
		3,
		3,
		5,
		5,
		4,
		4,
		4,
		4,
		4,
		2,
		7,
		7,
		8,
		12,
		3,
		4,
		5,
		1,
		3,
		4,
		4,
		10,
		4,
		3,
		3,
		3,
		8,
		7,
		7,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		12,
		9,
		20,
		7,
		5,
		5,
		5,
		9,
		13,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		16,
		5,
		5,
		5,
		13,
		7,
		8,
		8,
		11,
		8,
		7,
		9,
		7,
		11,
		12,
		9,
		9,
		8,
		8,
		11,
		10,
		14,
		7,
		12,
		10,
		11,
		13,
		7,
		9,
		11,
		17,
		17,
		14,
		13,
		7,
		8,
		7,
		10,
		10,
		7,
		16,
		13,
		7,
		8,
		17,
		12,
		9,
		8,
		6,
		7,
		10,
		6,
		6,
		12,
		6,
		8,
		10,
		8,
		8,
		8,
		6,
		8,
		6,
		14,
		6,
		6,
		6,
		13,
		6,
		10,
		6,
		6,
		7,
		14,
		8,
		6,
		6,
		10,
		11,
		10,
		9,
		9,
		7,
		7,
		6,
		6,
		6,
		9,
		9,
		7,
		9,
		10,
		9,
		13,
		12,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		6,
		6,
		8,
		8,
		6,
		8,
		9,
		10,
		9,
		7,
		10,
		10,
		8,
		7,
		8,
		7,
		10,
		12,
		9,
		8,
		15,
		8,
		7,
		8,
		8,
		7,
		7,
		15,
		13,
		7,
		10,
		9,
		14,
		18,
		16,
		7,
		24,
		7,
		8,
		10,
		11,
		16,
		8,
		14,
		7,
		9,
		9,
		9,
		13,
		19,
		14,
		15,
		14,
		11,
		7,
		13,
		9,
		10,
		7,
		13,
		9,
		10,
		11,
		12,
		8,
		9,
		2,
		3,
		5,
		8,
		7,
		4,
		4,
		15,
		10,
		5,
		3,
		3,
		3,
		3,
		3,
		5,
		4,
		4,
		4,
		2,
		2,
		2,
		2,
		2,
		1,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		4,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		2,
		12,
		5,
		3,
		8,
		10,
		15,
		6,
		7,
		2,
		3,
		2,
		5,
		5,
		12,
		2,
		5,
		5,
		5,
		5,
		2,
		2,
		5,
		5,
		12,
		9,
		5,
		2,
		2,
		9,
		5,
		5,
		12,
		12,
		5,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		9,
		12,
		5,
		8,
		8,
		9,
		5,
		5,
		5,
		8,
		19,
		7,
		16,
		15,
		14,
		9,
		9,
		9,
		9,
		7,
		11,
		11,
		11,
		7,
		14,
		10,
		10,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		15,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		9,
		9,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		14,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		15,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		12,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		9,
		9,
		12,
		9,
		9,
		12,
		12,
		12,
		15,
		7,
		11,
		7,
		14,
		11,
		18,
		13,
		8,
		18,
		15,
		18,
		12,
		14,
		12,
		8,
		8,
		8,
		8,
		9,
		9,
		9,
		12,
		7,
		10,
		10,
		8,
		8,
		12,
		12,
		12,
		7,
		12,
		12,
		9,
		7,
		7,
		7,
		7,
		7,
		8,
		15,
		12,
		9,
		10,
		10,
		7,
		10,
		10,
		13,
		11,
		10,
		9,
		22,
		11,
		9,
		8,
		8,
		8,
		8,
		8,
		13,
		18,
		13,
		9,
		15,
		19,
		9,
		7,
		7,
		10,
		7,
		7,
		7,
		11,
		8,
		13,
		17,
		7,
		7,
		10,
		10,
		10,
		7,
		20,
		16,
		7,
		7,
		7,
		7,
		7,
		7,
		11,
		21,
		12,
		12,
		13,
		11,
		14,
		16,
		8,
		8,
		13,
		11,
		7,
		7,
		13,
		7,
		7,
		14,
		15,
		15,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		13,
		10,
		18,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		11,
		8,
		8,
		12,
		12,
		11,
		11,
		8,
		12,
		9,
		9,
		9,
		13,
		13,
		9,
		9,
		9,
		9,
		9,
		9,
		6,
		10,
		12,
		6,
		6,
		6,
		6,
		17,
		11,
		7,
		7,
		7,
		7,
		14,
		14,
		12,
		6,
		7,
		7,
		6,
		6,
		15,
		10,
		13,
		10,
		6,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		7,
		13,
		9,
		9,
		15,
		13,
		6,
		12,
		12,
		6,
		19,
		11,
		10,
		7,
		7,
		16,
		8,
		19,
		17,
		9,
		9,
		9,
		9,
		9,
		6,
		6,
		6,
		10,
		8,
		16,
		8,
		6,
		6,
		9,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		8,
		8,
		8,
		6,
		7,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		14,
		6,
		6,
		6,
		6,
		20,
		6,
		9,
		6,
		14,
		9,
		9,
		9,
		6,
		9,
		8,
		8,
		12,
		9,
		8,
		8,
		8,
		8,
		7,
		8,
		12,
		7,
		8,
		8,
		8,
		6,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		8,
		8,
		6,
		6,
		13,
		9,
		12,
		13,
		12,
		14,
		13,
		12,
		11,
		11,
		6,
		8,
		8,
		8,
		6,
		13,
		12,
		11,
		11,
		12,
		6,
		11,
		12,
		11,
		13,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		15,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		13,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		8,
		8,
		8,
		8,
		6,
		18,
		6,
		12,
		13,
		13,
		13,
		9,
		10,
		15,
		9,
		12,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		15,
		10,
		9,
		10,
		13,
		9,
		19,
		8,
		18,
		17,
		10,
		10,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		10,
		14,
		8,
		16,
		16,
		9,
		8,
		15,
		8,
		8,
		10,
		12,
		14,
		7,
		7,
		8,
		8,
		7,
		7,
		7,
		7,
		8,
		13,
		13,
		11,
		9,
		9,
		9,
		12,
		10,
		17,
		8,
		11,
		9,
		7,
		7,
		14,
		8,
		14,
		14,
		7,
		7,
		7,
		7,
		7,
		7,
		14,
		7,
		7,
		7,
		7,
		7,
		10,
		10,
		8,
		14,
		7,
		7,
		7,
		7,
		8,
		8,
		8,
		8,
		8,
		17,
		9,
		7,
		15,
		7,
		8,
		12,
		7,
		9,
		14,
		7,
		7,
		7,
		9,
		13,
		8,
		14,
		7,
		16,
		18,
		13,
		15,
		14,
		12,
		13,
		10,
		15,
		9,
		7,
		7,
		7,
		10,
		13,
		15,
		15,
		9,
		9,
		9,
		9,
		19,
		11,
		7,
		11,
		11,
		13,
		8,
		8,
		8,
		8,
		7,
		12,
		19,
		17,
		9,
		9,
		13,
		7,
		7,
		7,
		9,
		7,
		7,
		7,
		12,
		13,
		15,
		10,
		8,
		8,
		14,
		15,
		12,
		13,
		13,
		8,
		12,
		14,
		7,
		11,
		7,
		14,
		15,
		13,
		12,
		8,
		8,
		8,
		8,
		11,
		13,
		15,
		15,
		8,
		13,
		12,
		8,
		8,
		8,
		13,
		10,
		16,
		14,
		11,
		8,
		8,
		12,
		12,
		9,
		15,
		15,
		12,
		12,
		13,
		8,
		8,
		9,
		12,
		13,
		9,
		8,
		8,
		8,
		8,
		8,
		8,
		8,
		8,
		8,
		8,
		8,
		11,
		12,
		11,
		7,
		14,
		7,
		13,
		13,
		13,
		12,
		18,
		16,
		7,
		12,
		11,
		10,
		10,
		15,
		9,
		9,
		9,
		21,
		7,
		7,
		7,
		11,
		16,
		8,
		8,
		11,
		11,
		7,
		7,
		7,
		7,
		7,
		19,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		12,
		8,
		9,
		12,
		14,
		11,
		9,
		9,
		9,
		22,
		12,
		3,
		3,
		4,
		8,
		8,
		15,
		4,
		2,
		2,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		6,
		4,
		4,
		4,
		12,
		7,
		10,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		7,
		3,
		7,
		5,
		14,
		4,
		4,
		7,
		8,
		10,
		4,
		1,
		3,
		3,
		6,
		2,
		4,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		4,
		2,
		2,
		5,
		3,
		4,
		2,
		2,
		2,
		2,
		2,
		2,
		11,
		5,
		5,
		5,
		11,
		5,
		5,
		3,
		5,
		5,
		5,
		5,
		11,
		14,
		13,
		9,
		11,
		9,
		12,
		8,
		11,
		11,
		8,
		11,
		16,
		9,
		9,
		7,
		10,
		9,
		12,
		8,
		15,
		6,
		7,
		6,
		6,
		13,
		10,
		8,
		11,
		8,
		6,
		6,
		6,
		12,
		16,
		6,
		11,
		7,
		8,
		9,
		18,
		6,
		6,
		9,
		4,
		4,
		6,
		13,
		6,
		6,
		6,
		6,
		8,
		8,
		9,
		16,
		7,
		7,
		14,
		7,
		8,
		8,
		8,
		7,
		7,
		7,
		7,
		7,
		7,
		15,
		13,
		7,
		10,
		7,
		7,
		10,
		12,
		16,
		15,
		7,
		9,
		9,
		14,
		11,
		11,
		10,
		9,
		10,
		8,
		12,
		7,
		8,
		7,
		7,
		10,
		12,
		7,
		12,
		8,
		7,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		3,
		3,
		5,
		5,
		5,
		10,
		4,
		8,
		7,
		10,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		1,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		7,
		4,
		5,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		6,
		6,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		9,
		8,
		2,
		2,
		2,
		8,
		12,
		7,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		8,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		5,
		7,
		11,
		9,
		8,
		8,
		8,
		7,
		8,
		9,
		7,
		7,
		9,
		7,
		7,
		7,
		10,
		7,
		7,
		10,
		9,
		10,
		6,
		6,
		6,
		6,
		6,
		6,
		15,
		7,
		8,
		9,
		9,
		8,
		6,
		6,
		10,
		9,
		6,
		8,
		13,
		9,
		7,
		6,
		6,
		6,
		6,
		6,
		6,
		12,
		6,
		6,
		7,
		6,
		7,
		6,
		6,
		6,
		10,
		10,
		7,
		6,
		6,
		6,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		6,
		14,
		6,
		6,
		7,
		7,
		9,
		6,
		6,
		6,
		6,
		9,
		9,
		8,
		9,
		10,
		9,
		8,
		9,
		12,
		7,
		7,
		7,
		8,
		7,
		10,
		12,
		11,
		9,
		10,
		7,
		7,
		7,
		9,
		10,
		10,
		8,
		12,
		9,
		7,
		7,
		9,
		8,
		8,
		8,
		10,
		7,
		7,
		8,
		9,
		9,
		7,
		7,
		7,
		8,
		2,
		4,
		6,
		3,
		4,
		2,
		3,
		3,
		3,
		3,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		4,
		4,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		8,
		6,
		4,
		7,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		12,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		2,
		3,
		5,
		3,
		4,
		7,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		3,
		3,
		6,
		4,
		3,
		4,
		2,
		2,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		5,
		4,
		4,
		4,
		4,
		7,
		6,
		8,
		9,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		5,
		7,
		2,
		3,
		3,
		8,
		7,
		7,
		2,
		2,
		8,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		8,
		8,
		7,
		7,
		6,
		10,
		6,
		9,
		7,
		11,
		4,
		6,
		8,
		8,
		7,
		8,
		4,
		5,
		5,
		5,
		5,
		3,
		3,
		11,
		8,
		9,
		6,
		6,
		8,
		7,
		4,
		4,
		7,
		8,
		7,
		2,
		2,
		3,
		3,
		3,
		3,
		4,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		7,
		2,
		2,
		5,
		3,
		3,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		2,
		2,
		2,
		2,
		2,
		12,
		5,
		5,
		3,
		3,
		3,
		5,
		10,
		12,
		6,
		15,
		4,
		6,
		6,
		7,
		14,
		9,
		3,
		3,
		3,
		3,
		3,
		8,
		2,
		2,
		3,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		8,
		8,
		8,
		7,
		5,
		8,
		4,
		6,
		11,
		2,
		2,
		6,
		7,
		3,
		3,
		2,
		9,
		8,
		5,
		5,
		3,
		3,
		3,
		5,
		5,
		7,
		7,
		6,
		6,
		10,
		6,
		8,
		6,
		8,
		9,
		7,
		4,
		4,
		4,
		4,
		7,
		6,
		6,
		7,
		7,
		10,
		9,
		8,
		11,
		8,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		7,
		6,
		2,
		5,
		6,
		7,
		6,
		4,
		8,
		9,
		11,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		9,
		9,
		6,
		4,
		8,
		7,
		7,
		5,
		9,
		8,
		6,
		2,
		8,
		7,
		8,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		16,
		8,
		7,
		7,
		7,
		8,
		7,
		7,
		7,
		7,
		9,
		6,
		9,
		6,
		10,
		7,
		7,
		7,
		6,
		10,
		8,
		9,
		11,
		11,
		8,
		4,
		4,
		10,
		8,
		8,
		6,
		9,
		6,
		11,
		8,
		8,
		8,
		15,
		7,
		8,
		9,
		5,
		3,
		3,
		3,
		3,
		3,
		5,
		11,
		2,
		2,
		3,
		8,
		9,
		10,
		3,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		6,
		4,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		11,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		7,
		4,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		12,
		7,
		4,
		12,
		4,
		6,
		5,
		4,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		4,
		11,
		10,
		6,
		4,
		6,
		10,
		8,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		4,
		4,
		4,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		5,
		3,
		4,
		4,
		1,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		10,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		7,
		8,
		8,
		7,
		13,
		12,
		10,
		10,
		8,
		8,
		7,
		7,
		9,
		12,
		11,
		6,
		6,
		8,
		8,
		9,
		7,
		7,
		7,
		10,
		15,
		10,
		4,
		4,
		4,
		4,
		4,
		11,
		8,
		8,
		9,
		7,
		9,
		14,
		14,
		12,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		12,
		5,
		5,
		5,
		11,
		10,
		7,
		9,
		3,
		8,
		7,
		3,
		15,
		13,
		11,
		4,
		4,
		2,
		2,
		2,
		19,
		7,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		22,
		18,
		6,
		14,
		17,
		4,
		4,
		19,
		16,
		18,
		2,
		3,
		3,
		7,
		2,
		3,
		2,
		3,
		3,
		6,
		4,
		2,
		3,
		3,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		9,
		9,
		2,
		3,
		2,
		2,
		2,
		3,
		3,
		3,
		5,
		7,
		14,
		7,
		7,
		12,
		9,
		13,
		6,
		11,
		6,
		10,
		9,
		7,
		7,
		8,
		12,
		12,
		8,
		8,
		8,
		10,
		7,
		7,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		5,
		8,
		10,
		7,
		8,
		11,
		8,
		12,
		9,
		4,
		14,
		7,
		7,
		9,
		13,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		2,
		3,
		3,
		3,
		1,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		2,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		8,
		4,
		4,
		4,
		3,
		2,
		3,
		3,
		3,
		3,
		5,
		2,
		2,
		2,
		2,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		7,
		7,
		7,
		7,
		7,
		8,
		8,
		8,
		8,
		8,
		12,
		9,
		8,
		8,
		9,
		8,
		6,
		17,
		6,
		6,
		6,
		8,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		7,
		4,
		4,
		8,
		8,
		9,
		9,
		9,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		9,
		9,
		9,
		7,
		8,
		8,
		8,
		10,
		7,
		13,
		10,
		8,
		9,
		3,
		3,
		5,
		13,
		3,
		3,
		3,
		3,
		3,
		7,
		7,
		6,
		6,
		10,
		13,
		11,
		11,
		8,
		8,
		9,
		8,
		9,
		9,
		10,
		10,
		10,
		11,
		10,
		10,
		13,
		13,
		16,
		15,
		11,
		12,
		9,
		9,
		10,
		9,
		11,
		10,
		9,
		9,
		14,
		7,
		8,
		3,
		10,
		7,
		7,
		3,
		2,
		2,
		2,
		5,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		7,
		2,
		2,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		4,
		11,
		6,
		7,
		4,
		6,
		2,
		2,
		3,
		3,
		3,
		1,
		3,
		3,
		3,
		3,
		3,
		3,
		6,
		4,
		4,
		2,
		2,
		2,
		3,
		3,
		3,
		3,
		4,
		4,
		6,
		6,
		6,
		6,
		5,
		4,
		4,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		2,
		9,
		11,
		6,
		10,
		9,
		12,
		7,
		7,
		11,
		14,
		9,
		7,
		12,
		3,
		3,
		7,
		12,
		11,
		12,
		7,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		9,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		11,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		11,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		3,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		3,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		3,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		6,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		5,
		3,
		10,
		3,
		3,
		3,
		11,
		3,
		5,
		9,
		11,
		8,
		12,
		14,
		9,
		7,
		8,
		7,
		7,
		11,
		11,
		7,
		7,
		10,
		9,
		8,
		10,
		9,
		7,
		7,
		7,
		7,
		7,
		7,
		8,
		8,
		7,
		11,
		8,
		8,
		8,
		7,
		7,
		10,
		8,
		7,
		13,
		12,
		7,
		17,
		10,
		8,
		8,
		11,
		7,
		11,
		11,
		14,
		7,
		11,
		7,
		8,
		6,
		9,
		20,
		8,
		7,
		9,
		16,
		7,
		10,
		6,
		11,
		10,
		8,
		9,
		7,
		16,
		11,
		11,
		9,
		8,
		9,
		8,
		8,
		8,
		11,
		8,
		15,
		8,
		8,
		9,
		7,
		8,
		8,
		11,
		10,
		7,
		5,
		7,
		10,
		10,
		15,
		7,
		7,
		7,
		8,
		7,
		8,
		8,
		10,
		11,
		10,
		10,
		10,
		11,
		11,
		7,
		8,
		6,
		8,
		8,
		8,
		10,
		6,
		8,
		6,
		6,
		7,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		16,
		6,
		15,
		6,
		7,
		11,
		11,
		7,
		9,
		10,
		11,
		13,
		10,
		6,
		16,
		8,
		10,
		12,
		11,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		10,
		6,
		10,
		7,
		7,
		7,
		7,
		11,
		7,
		11,
		6,
		6,
		6,
		6,
		6,
		6,
		17,
		7,
		7,
		6,
		6,
		12,
		22,
		6,
		6,
		6,
		6,
		6,
		8,
		6,
		6,
		6,
		6,
		7,
		6,
		6,
		5,
		6,
		6,
		8,
		11,
		6,
		9,
		14,
		11,
		9,
		11,
		7,
		7,
		8,
		6,
		6,
		6,
		8,
		10,
		9,
		6,
		6,
		6,
		6,
		9,
		7,
		6,
		6,
		6,
		6,
		6,
		15,
		6,
		4,
		4,
		4,
		6,
		4,
		17,
		8,
		11,
		6,
		6,
		9,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		7,
		6,
		6,
		6,
		6,
		10,
		6,
		10,
		6,
		6,
		6,
		6,
		12,
		8,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		9,
		6,
		6,
		6,
		6,
		18,
		6,
		6,
		6,
		8,
		9,
		10,
		7,
		8,
		9,
		10,
		11,
		7,
		13,
		6,
		8,
		8,
		6,
		6,
		14,
		7,
		7,
		7,
		7,
		10,
		7,
		14,
		9,
		6,
		6,
		9,
		15,
		9,
		7,
		14,
		6,
		11,
		14,
		13,
		7,
		12,
		8,
		7,
		7,
		7,
		7,
		7,
		12,
		7,
		10,
		9,
		16,
		6,
		8,
		6,
		5,
		17,
		6,
		8,
		10,
		4,
		6,
		4,
		10,
		15,
		17,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		4,
		8,
		4,
		4,
		11,
		7,
		4,
		4,
		7,
		7,
		7,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		6,
		19,
		17,
		6,
		10,
		11,
		6,
		6,
		6,
		6,
		18,
		6,
		6,
		11,
		4,
		4,
		4,
		5,
		6,
		6,
		6,
		9,
		5,
		6,
		4,
		6,
		6,
		4,
		6,
		6,
		6,
		6,
		10,
		6,
		6,
		4,
		6,
		6,
		10,
		6,
		10,
		6,
		6,
		6,
		6,
		11,
		6,
		6,
		10,
		6,
		6,
		8,
		6,
		6,
		6,
		8,
		6,
		11,
		4,
		11,
		9,
		10,
		9,
		11,
		4,
		8,
		4,
		11,
		12,
		7,
		9,
		8,
		6,
		7,
		7,
		8,
		12,
		12,
		11,
		13,
		10,
		11,
		7,
		7,
		7,
		9,
		7,
		11,
		10,
		7,
		7,
		7,
		16,
		11,
		10,
		11,
		17,
		9,
		9,
		8,
		8,
		7,
		7,
		7,
		9,
		7,
		7,
		7,
		14,
		7,
		13,
		9,
		11,
		10,
		14,
		10,
		10,
		12,
		11,
		10,
		7,
		10,
		5,
		14,
		8,
		8,
		8,
		9,
		7,
		8,
		7,
		7,
		9,
		8,
		7,
		8,
		7,
		7,
		7,
		7,
		7,
		7,
		7,
		11,
		8,
		10,
		8,
		7,
		8,
		14,
		11,
		8,
		9,
		9,
		9,
		8,
		24,
		10,
		10,
		12,
		7,
		7,
		15,
		11,
		8,
		8,
		12,
		11,
		8,
		9,
		9,
		7,
		8,
		9,
		10,
		11,
		10,
		11,
		7,
		12,
		7,
		7,
		11,
		9,
		8,
		14,
		13,
		12,
		8,
		11,
		10,
		8,
		8,
		7,
		7,
		14,
		9,
		10,
		8,
		9,
		11,
		7,
		14,
		8,
		8,
		13,
		8,
		8,
		12,
		7,
		10,
		14,
		14,
		11,
		9,
		10,
		9,
		9,
		7,
		7,
		11,
		11,
		13,
		9,
		13,
		5,
		5,
		5,
		7,
		9,
		5,
		11,
		12,
		14,
		8,
		7,
		7,
		11,
		10,
		9,
		7,
		8,
		8,
		7,
		10,
		11,
		11,
		5,
		5,
		7,
		5,
		5,
		5,
		7,
		7,
		15,
		7,
		7,
		8,
		7,
		15,
		12,
		12,
		10,
		7,
		8,
		7,
		11,
		7,
		7,
		7,
		23,
		11,
		8,
		8,
		11,
		10,
		7,
		8,
		11,
		7,
		19,
		7,
		7,
		6,
		9,
		9,
		9,
		11,
		3,
		4,
		7,
		8,
		6,
		6,
		4,
		10,
		8,
		2,
		2
	]);
	const edgeChild = /*#__PURE__*/ new Uint16Array([
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		17,
		1,
		1,
		1,
		12,
		1,
		12,
		1,
		12,
		13,
		1,
		1,
		1,
		1,
		12,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		14,
		21,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		19,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		20,
		1,
		1,
		1,
		16,
		18,
		1,
		1,
		15,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		22,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		1,
		24,
		25,
		26,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		1,
		1,
		12,
		12,
		12,
		12,
		1,
		32,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		35,
		34,
		1,
		1,
		1,
		1,
		1,
		33,
		1,
		1,
		1,
		1,
		37,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		38,
		0,
		0,
		0,
		0,
		39,
		40,
		0,
		0,
		0,
		0,
		12,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		43,
		44,
		44,
		44,
		43,
		44,
		43,
		43,
		45,
		44,
		43,
		44,
		43,
		43,
		43,
		43,
		43,
		43,
		45,
		43,
		43,
		43,
		43,
		43,
		43,
		44,
		46,
		46,
		44,
		43,
		43,
		43,
		43,
		43,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		49,
		51,
		49,
		49,
		49,
		51,
		49,
		50,
		49,
		52,
		49,
		50,
		50,
		49,
		49,
		49,
		50,
		52,
		50,
		52,
		49,
		50,
		50,
		12,
		54,
		54,
		53,
		55,
		50,
		52,
		49,
		49,
		47,
		48,
		56,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		59,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		1,
		1,
		66,
		1,
		12,
		1,
		1,
		65,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		77,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		75,
		78,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		76,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		88,
		1,
		90,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		93,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		96,
		96,
		1,
		1,
		12,
		1,
		99,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		97,
		1,
		98,
		1,
		100,
		1,
		1,
		1,
		1,
		1,
		101,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		109,
		110,
		1,
		1,
		1,
		1,
		1,
		1,
		112,
		112,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		120,
		121,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		121,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		121,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		125,
		122,
		124,
		119,
		1,
		123,
		1,
		1,
		113,
		1,
		1,
		1,
		1,
		116,
		1,
		126,
		1,
		1,
		1,
		1,
		1,
		1,
		118,
		1,
		107,
		1,
		108,
		1,
		12,
		127,
		105,
		1,
		111,
		1,
		1,
		1,
		1,
		1,
		106,
		114,
		1,
		12,
		12,
		12,
		117,
		115,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		1,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		12,
		133,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		135,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		136,
		137,
		12,
		12,
		134,
		132,
		44,
		44,
		139,
		49,
		49,
		138,
		141,
		140,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		144,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		142,
		0,
		0,
		0,
		0,
		1,
		0,
		143,
		131,
		1,
		0,
		1,
		1,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		147,
		146,
		20,
		1,
		1,
		12,
		12,
		1,
		20,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		133,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		152,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		1,
		1,
		135,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		152,
		1,
		1,
		133,
		1,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		152,
		1,
		1,
		133,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		133,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		159,
		1,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		1,
		152,
		1,
		1,
		159,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		133,
		1,
		1,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		152,
		1,
		1,
		1,
		133,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		163,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		1,
		166,
		1,
		1,
		159,
		1,
		1,
		1,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		1,
		152,
		1,
		1,
		159,
		1,
		1,
		1,
		1,
		1,
		151,
		1,
		1,
		1,
		1,
		1,
		152,
		1,
		153,
		157,
		157,
		12,
		1,
		12,
		165,
		1,
		1,
		1,
		1,
		1,
		157,
		157,
		157,
		153,
		1,
		1,
		1,
		156,
		157,
		160,
		164,
		1,
		1,
		1,
		1,
		156,
		156,
		1,
		1,
		155,
		153,
		153,
		156,
		169,
		155,
		169,
		1,
		1,
		167,
		1,
		155,
		154,
		156,
		1,
		1,
		1,
		1,
		156,
		1,
		158,
		1,
		1,
		1,
		12,
		1,
		161,
		1,
		161,
		1,
		1,
		1,
		161,
		160,
		162,
		168,
		155,
		153,
		1,
		1,
		1,
		1,
		1,
		1,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		171,
		172,
		171,
		172,
		171,
		171,
		171,
		171,
		173,
		173,
		171,
		172,
		171,
		172,
		171,
		171,
		12,
		1,
		12,
		12,
		12,
		12,
		1,
		12,
		12,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		195,
		1,
		1,
		1,
		1,
		12,
		201,
		202,
		203,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		150,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		198,
		1,
		1,
		1,
		185,
		1,
		1,
		1,
		1,
		209,
		1,
		1,
		206,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		176,
		192,
		1,
		1,
		1,
		188,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		183,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		193,
		1,
		1,
		1,
		1,
		197,
		1,
		1,
		1,
		1,
		170,
		1,
		1,
		191,
		1,
		1,
		1,
		194,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		181,
		1,
		12,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		184,
		1,
		1,
		1,
		190,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		210,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		196,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		175,
		12,
		1,
		1,
		1,
		178,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		200,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		177,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		205,
		1,
		1,
		1,
		182,
		1,
		1,
		1,
		189,
		1,
		12,
		1,
		186,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		193,
		1,
		1,
		1,
		1,
		180,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		174,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		187,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		207,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		208,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		179,
		1,
		1,
		1,
		187,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		199,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		204,
		1,
		1,
		12,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		220,
		0,
		0,
		0,
		0,
		0,
		221,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		12,
		1,
		1,
		1,
		225,
		1,
		1,
		1,
		0,
		226,
		223,
		224,
		1,
		1,
		1,
		1,
		1,
		1,
		231,
		1,
		233,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		229,
		1,
		1,
		1,
		1,
		1,
		235,
		1,
		1,
		12,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		234,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		230,
		1,
		1,
		1,
		228,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		232,
		1,
		1,
		1,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		12,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		241,
		13,
		1,
		1,
		1,
		12,
		12,
		238,
		239,
		1,
		1,
		1,
		1,
		240,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		242,
		1,
		1,
		12,
		16,
		1,
		1,
		1,
		1,
		1,
		1,
		243,
		1,
		1,
		1,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		243,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		252,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		256,
		256,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		12,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		171,
		261,
		262,
		1,
		12,
		1,
		1,
		1,
		1,
		12,
		264,
		1,
		1,
		263,
		1,
		1,
		266,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		270,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		12,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		0,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		12,
		0,
		281,
		0,
		0,
		282,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		12,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		59,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		0,
		1,
		1,
		1,
		0,
		306,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		308,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		324,
		324,
		325,
		324,
		0,
		187,
		1,
		1,
		13,
		320,
		1,
		318,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		321,
		1,
		1,
		326,
		1,
		206,
		1,
		1,
		1,
		1,
		319,
		1,
		316,
		1,
		322,
		1,
		314,
		1,
		323,
		1,
		315,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		12,
		317,
		317,
		1,
		1,
		1,
		185,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		313,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		329,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		266,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		369,
		369,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		361,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		1,
		1,
		1,
		0,
		1,
		337,
		348,
		1,
		1,
		336,
		371,
		1,
		342,
		1,
		1,
		334,
		366,
		1,
		1,
		352,
		333,
		338,
		1,
		1,
		1,
		345,
		376,
		354,
		1,
		1,
		1,
		1,
		1,
		1,
		355,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		1,
		0,
		364,
		368,
		0,
		0,
		78,
		1,
		1,
		0,
		362,
		339,
		375,
		340,
		343,
		350,
		1,
		365,
		0,
		1,
		0,
		78,
		359,
		357,
		1,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		378,
		1,
		1,
		349,
		1,
		78,
		1,
		0,
		1,
		1,
		1,
		381,
		1,
		0,
		0,
		78,
		356,
		0,
		1,
		335,
		1,
		1,
		1,
		0,
		1,
		1,
		358,
		1,
		0,
		1,
		1,
		1,
		0,
		1,
		383,
		346,
		1,
		1,
		0,
		1,
		0,
		0,
		374,
		0,
		1,
		1,
		1,
		78,
		367,
		1,
		1,
		363,
		360,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		341,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		373,
		0,
		78,
		1,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		1,
		1,
		377,
		1,
		1,
		1,
		0,
		0,
		380,
		0,
		0,
		0,
		1,
		353,
		1,
		0,
		78,
		379,
		1,
		0,
		0,
		0,
		0,
		382,
		1,
		1,
		0,
		0,
		1,
		0,
		1,
		0,
		351,
		0,
		347,
		0,
		1,
		1,
		1,
		0,
		1,
		1,
		0,
		370,
		344,
		372,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		12,
		1,
		1,
		1,
		12,
		398,
		398,
		1,
		1,
		12,
		12,
		1,
		398,
		1,
		1,
		12,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		410,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		206,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		428,
		428,
		1,
		1,
		0,
		0,
		314,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		441,
		1,
		440,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		445,
		1,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		453,
		1,
		1,
		1,
		455,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		452,
		1,
		447,
		1,
		1,
		1,
		1,
		434,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		448,
		12,
		1,
		1,
		1,
		1,
		454,
		1,
		1,
		1,
		449,
		443,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		314,
		1,
		431,
		1,
		1,
		12,
		451,
		1,
		1,
		314,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		436,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		454,
		1,
		1,
		1,
		1,
		314,
		1,
		450,
		1,
		1,
		1,
		444,
		438,
		1,
		1,
		1,
		1,
		1,
		439,
		1,
		456,
		442,
		1,
		1,
		1,
		1,
		1,
		437,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		432,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		446,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		435,
		1,
		1,
		1,
		1,
		1,
		433,
		1,
		220,
		457,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		12,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		0,
		1,
		0,
		0,
		1,
		0,
		1,
		0,
		1,
		1,
		0,
		0,
		0,
		463,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		12,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		467,
		0,
		467,
		467,
		467,
		467,
		467,
		467,
		467,
		0,
		467,
		467,
		467,
		467,
		467,
		1,
		467,
		467,
		467,
		0,
		467,
		467,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		472,
		471,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		476,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		469,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		470,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		478,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		467,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		475,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		468,
		0,
		0,
		479,
		474,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		473,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		467,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		468,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		467,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		477,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		489,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		200,
		200,
		1,
		493,
		1,
		1,
		1,
		492,
		1,
		1,
		1,
		1,
		488,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		490,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		494,
		1,
		1,
		491,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		369,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		495,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		506,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		0,
		12,
		1,
		508,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		12,
		12,
		1,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		1,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		0,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		59,
		1,
		1,
		12,
		12,
		12,
		12,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		527,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		528,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		526,
		1,
		1,
		12,
		1,
		1,
		530,
		239,
		1,
		1,
		12,
		12,
		1,
		1,
		12,
		1,
		12,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		534,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		540,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		131,
		1,
		12,
		545,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		106,
		1,
		1,
		12,
		1,
		1,
		1,
		12,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		550,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		12,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		143,
		1,
		1,
		1,
		228,
		1,
		1,
		12,
		30,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		1,
		575,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		220,
		1,
		325,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		580,
		1,
		1,
		1,
		1,
		0,
		582,
		0,
		78,
		0,
		581,
		0,
		1,
		1,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		0,
		0,
		0,
		1,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		589,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		0,
		0,
		1,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		584,
		584,
		0,
		588,
		586,
		584,
		584,
		584,
		584,
		584,
		590,
		584,
		584,
		594,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		591,
		588,
		584,
		584,
		588,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		584,
		586,
		584,
		584,
		584,
		584,
		584,
		592,
		584,
		584,
		584,
		584,
		584,
		584,
		0,
		0,
		0,
		1,
		593,
		1,
		1,
		1,
		1,
		587,
		1,
		1,
		1,
		1,
		1,
		585,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		12,
		598,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		1,
		12,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		12,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		1,
		12,
		1,
		1,
		12,
		0,
		0,
		0,
		0,
		0,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		1,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		95,
		64,
		278,
		304,
		409,
		536,
		0,
		4,
		67,
		236,
		254,
		280,
		305,
		331,
		385,
		411,
		0,
		500,
		520,
		537,
		600,
		9,
		0,
		60,
		87,
		395,
		407,
		427,
		578,
		0,
		498,
		519,
		533,
		615,
		0,
		30,
		6,
		0,
		462,
		501,
		605,
		563,
		69,
		0,
		7,
		283,
		255,
		386,
		464,
		414,
		539,
		78,
		601,
		0,
		579,
		307,
		416,
		466,
		9,
		104,
		286,
		507,
		6,
		30,
		0,
		309,
		78,
		388,
		78,
		484,
		10,
		6,
		130,
		248,
		273,
		0,
		616,
		510,
		0,
		566,
		0,
		63,
		6,
		6,
		251,
		94,
		2,
		430,
		396,
		408,
		599,
		0,
		6,
		0,
		6,
		284,
		102,
		6,
		564,
		502,
		541,
		0,
		465,
		387,
		271,
		285,
		8,
		70,
		103,
		602,
		544,
		389,
		310,
		298,
		417,
		145,
		73,
		288,
		548,
		511,
		604,
		567,
		332,
		327,
		480,
		6,
		74,
		148,
		11,
		0,
		249,
		523,
		549,
		568,
		515,
		553,
		573,
		614,
		36,
		6,
		260,
		293,
		330,
		302,
		218,
		30,
		529,
		556,
		218,
		41,
		216,
		265,
		294,
		303,
		404,
		421,
		482,
		272,
		0,
		72,
		565,
		0,
		401,
		415,
		297,
		78,
		247,
		78,
		0,
		583,
		547,
		505,
		290,
		419,
		78,
		390,
		384,
		0,
		0,
		0,
		9,
		558,
		574,
		217,
		0,
		422,
		405,
		532,
		517,
		576,
		618,
		84,
		218,
		42,
		295,
		393,
		423,
		572,
		0,
		512,
		291,
		274,
		78,
		215,
		79,
		28,
		387,
		30,
		6,
		391,
		328,
		301,
		607,
		595,
		525,
		552,
		514,
		0,
		258,
		80,
		30,
		403,
		420,
		0,
		30,
		424,
		0,
		219,
		596,
		518,
		9,
		406,
		425,
		218,
		248,
		85,
		222,
		597,
		577,
		560,
		483,
		426,
		394,
		250,
		227,
		86,
		58,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		623,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		412,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		81,
		0,
		128,
		0,
		0,
		83,
		551,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		27,
		0,
		554,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		412,
		0,
		0,
		0,
		0,
		504,
		0,
		257,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		292,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		620,
		0,
		0,
		0,
		0,
		0,
		619,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		392,
		0,
		0,
		0,
		485,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		68,
		0,
		0,
		0,
		0,
		0,
		0,
		496,
		0,
		0,
		0,
		0,
		0,
		0,
		402,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		211,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		516,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		497,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		269,
		279,
		0,
		0,
		0,
		0,
		0,
		531,
		275,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		513,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		458,
		0,
		0,
		0,
		312,
		0,
		0,
		0,
		0,
		0,
		0,
		253,
		0,
		0,
		0,
		0,
		0,
		0,
		23,
		0,
		0,
		0,
		0,
		571,
		0,
		0,
		0,
		0,
		603,
		522,
		0,
		0,
		0,
		0,
		244,
		0,
		0,
		0,
		0,
		0,
		0,
		460,
		0,
		0,
		481,
		0,
		0,
		0,
		0,
		0,
		61,
		0,
		0,
		0,
		267,
		57,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		246,
		0,
		0,
		0,
		0,
		0,
		277,
		613,
		0,
		71,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		622,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		149,
		0,
		276,
		0,
		0,
		0,
		0,
		0,
		0,
		570,
		0,
		0,
		0,
		0,
		0,
		0,
		524,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		569,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		62,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		213,
		0,
		0,
		0,
		0,
		0,
		3,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		83,
		0,
		503,
		0,
		0,
		0,
		0,
		0,
		557,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		83,
		82,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		487,
		0,
		486,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		259,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		459,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		287,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		538,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		296,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		68,
		237,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		83,
		0,
		609,
		0,
		0,
		555,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		245,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		612,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		521,
		0,
		0,
		0,
		83,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		499,
		0,
		617,
		0,
		0,
		429,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		400,
		0,
		0,
		0,
		546,
		0,
		92,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		31,
		0,
		0,
		0,
		0,
		0,
		0,
		29,
		91,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		289,
		0,
		0,
		0,
		214,
		0,
		0,
		0,
		0,
		0,
		0,
		561,
		0,
		0,
		0,
		0,
		129,
		0,
		0,
		0,
		0,
		0,
		562,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		412,
		418,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		397,
		0,
		311,
		0,
		0,
		0,
		0,
		0,
		5,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		299,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		535,
		0,
		0,
		0,
		413,
		0,
		0,
		399,
		0,
		0,
		0,
		0,
		0,
		0,
		606,
		0,
		0,
		0,
		542,
		0,
		0,
		89,
		0,
		543,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		509,
		461,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		268,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		412,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		611,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		610,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		621,
		0,
		0,
		0,
		0,
		0,
		559,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		300,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		608,
		0,
		0,
		212,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		0,
		626,
		626,
		626,
		626,
		626,
		626,
		626,
		625,
		627
	]);
	const labelText = "orgmilcomschnetedugovdrrformsfeedbackofficialaccoorgmilschnetgovmagazinemediaunioncargopilotgroupcaarespressworksaerodromeworkinggroupair-traffic-controlaircraftaccident-preventioneducatormarketplaceambulanceinsurancecateringairportrepbodyenginesoftwaremodellingair-surveillanceconsultingchartertrainermaintenanceservicesdesignflightskydivingfreightassociationstudentgroundhandlingdgcafuelclubtaxicrewshowballooningexpresstraderbrokerauthoragentsairtrafficjournalistsafetyconsultantmicrolightaccident-investigationparachutingequipmentproductionfederationrecreationscientistnavigationengineertradingglidingleasingresearchpassenger-associationentertainmentparaglidinghangglidingaerobaticrotorcraftemergencycertificationgovernmentaeroclubexchangelogisticschampionshiphomebuiltcouncilconferencecontrolairlinecivilaviationjournalorgcomnetedugovcoorgcomnomnetobjofforgcomnetuwukiloappsframerorgmilcomnetedugovcoradioorgcomnetcommuneedogpbcoitgvorgedugov*spreviewfrontendrelayononstagingupid*mtls*privatelinktypedreamdeveloperbravemochawindsurfaivenmirenupsunwnextbegetngrokclerkwale2bwebcsbrunputerflutterflowspawnbaseshiptodaymagicpatternsnetlifyondigitaloceanrailwayhostedclaudehasurabotdashvercelgithubluyanigadgetreplitcloudflaretelebitedgecomputeevervaultexponyatnoopencrpplxzeaburwasmerframerzeropsrocketpreviewconvexmedusajsspritesonherculeseasypanelstreamlitsnowflakemesserliloginlinehackclubcodepennorthflankbase44corespeedleapcellngrok-freeclerkstagelovableon-fleek*us-west-3ap-south-2us-central-2us-central-1eu-central-1ap-south-1us-west-2us-east-2eu-north-1ap-north-1us-west-1us-east-1*rcloudintsegorgmilcomgobbetnetintedugovturmusicasenasamutualcoopip6uriurnin-addre164homeirisgovdixdaemoncloudnssthwien*inexexkunden4accogvormymyspreadshop4lima2ixortsinfofuturecmsfuturehosting12hpprivfuturemailinglima-cityfunkfeuer123webseitednshomemelmyspreadshopcloudletswasantqldvicactnswtascatholicwasaqldvictasidwasantozqldorgcomvicasnactnetedugovnswtasconfcomairflowlambda-urltransfer-webappairflowtransfer-webapptransfer-webapptransfer-webapp-fipstransfer-webappeu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1privatenotebookstudiolabelingnotebookstudionotebooknotebook-fipslabelingnotebookstudionotebook-fipsnotebookstudio-fipsnotebook-fipsnotebookstudionotebook-fipsnotebookstudioeu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2experimentsus-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1onrepostsagemakercopporgmilcompronetintedugovbiznameinfoshoprsorgmilcomnetedugovbrendlyresolvenzauscotvstoreorgcomnetedugovbizinfoidacaicoittvorgmilcomschnetedugovinfocloudezproxyacmymyspreadshopkuleuvenwebhostingtransurl123websitecloudnsinterhostsolutionsddns5476103298edgfacbmlonihkjutwvqpsryxzbarsycoororgcomedumyftpno-iporxcloud-ipfor-somemmafanfor-morewebhopselfipjozidyndnscloudnsdscloudfor-thefor-betteractivetrailcoeconorestooteorgcomeconeteduassurmoneyafricaarchitectesrestaurantloisirstourismavocatsinfoagrounivcoorgcomnetedugoviatvdeportesaludtksatorgmilcomwebgobnetinteducienciaboliviarevistacooperativaempresanombreindustriamusicapatriamedicinademocraciapoliticapuebloindigenaplurinacionalarteblogwikiinfoagrotransportenoticiasprofesionalacademiaeconomiaecologiamovimientotecnologianaturalsimplesitecepesebamapadfmgalampbacscpirngorotomtrjspaprrprrsesmscepesebamapadfmgalampbacscpirngorotomtrjspaprrprrsesms*biaamfmtcmptvfeirasampajampanatalbelemananiradiog12medindfndbmdtrdthepoaggfjdfdefinfenflegsegongengcngorgzlgslglogppgmillelqslcimcomnomadmjabimbbibbsbabcrectecsjcetcpscpvhudieticriapipsiecnbiorioecogeoteoodoproatoartfstmatvetdetbetnetcntnotfotgrueduajuespappreptmpemparqsrvadvdevgovntrturagrjorfarjusmusdesvixxyzcozfozslzbhzmaringasantamariacampinagrandegoianiasorocabafloripasaobernardocuritibaboavistarecifeaparecidasaogoncasalvadorcuiabamorenamacapalondrinacontagemsocialfortalmaceioleilaoosascoriobranconiteroi9guacutcheblogflogvlogwikitaxicoopmanauspalmascaxiasjoinvillebaruericampinassantoandreribeiraoriopretoweorgcomnetedugovv0windsurfshiptodaycloudsitecoaccoorgnetgovofmilcomgovmediatechzacoorgcomnetedugsjgovmydnspenfnlabnbmbgcbcqconcontnuyksknsmyspreadshopno-ipawdevboxbarsyonidatemfuinabusavinstanceseceuguukussryzespawncsxcloud-ipmyphotosfantasyleaguetwmailcleverappsscrappingccwucloudnsftpaccessgame-serverccgovobjectsrmalpgcust*svcalp1aeappenginermalpgmyspreadshop4lima2ixsquare7cloudscale123websitefirenet12hpflowgotdnslinkyard-cloudcloudnslima-citydnskingobjectstorageedaccogoorusorgcomnetinteduaéroportxn--aroport-byaassogouvcomilgobgovcloudnses-1eu-west-1us-east-1euvipit1eurarubait1s3lbwebsites3websiteru-spbru-mskelasticcsrunstnukukcaukusnl-ams-1fr-par-1fr-par-2functionsnodess3ddlwhmrdbfnck8sifrs3-websitecockpitscblmgdbdtwhkafkpubprivs3ddlwhmrdbk8sifrs3-websitecockpitscblmgdbdtwhkafks3ddlrdbk8sifrs3-websitecockpitscblmgdbdtwhkafkk8sscalebookpl-wawfr-parnl-amsbaremetalsmartlabelinginstancesdechk2kuleuvenlaravelvoorloperurownoxazapscwhstgrvaporonline-serverobservablehqelementorantagonistreclaimjoteluluencowaydiademjelasticmatlabmagentositetrendhostingaxarnetperspectajenv-arubajelejoteravendbemergenttrafficplexconvexkeliwebserveboltbegetcdnstaticson-rancherprimetelonstackitunison-servicesdnshomelinkyardbarsyjelecloudnscocomnetgovmycn-northwest-1cn-north-1s3s3-accesspoints3-websites3s3-accesspointrdsdualstacks3-deprecatedemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspoints3s3-accesspointrdsdualstackemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicn-northwest-1cn-north-1cn-northwest-1ebcomputeelbcn-north-1airflowcn-northwest-1cn-north-1oncn-northwest-1cn-north-1amazonawssagemakeramazonwebservicesdirectasgdsdhehahljlnmhbacscahqhshhihnlnynsnmofjbjzjxjtjhkcqtwgsjssxnxjxgxxzgz網絡网络公司orgmilcomnetedugovxn--55qx5dcanva-appsxn--io0a7iquickconnectcanvasitekhsjxn--od0algcanva-codemyqnapcloudsrvrlessclustersrealtimestorageleadpagescarrdcrdorgmilcomnomnetedugovhidnssupabaserdpareplmypiumsoxmitotaplpagesfirewalledreplitowodevwebview-assetsvfswebview-assetss3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9eu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1s3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackanalytics-gatewayemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspointdualstacks3-deprecateds3-websites3-object-lambdaexecute-apis3s3-accesspoints3-websites3-accesspoint-fipss3-fipss3s3-accesspointdualstackemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackemrappui-prods3-websites3-accesspoint-fipss3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9vfss3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9eu-west-3ap-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1us-northeast-1ap-southeast-1me-south-1af-south-1ap-south-1ap-southeast-7us-west-2eu-west-2ap-east-2us-east-2ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ap-southeast-6ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1mrapaccesspoints3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3eu-west-3ap-south-2eu-south-2computes3-ap-northeast-2elbrdss3-ap-east-1s3-sa-east-1s3-us-gov-west-1s3-eu-central-1s3-ca-central-1eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3s3-website-us-west-2s3-website-eu-west-1s3-external-1eu-central-1me-central-1ca-central-1il-central-1s3-us-west-1s3-eu-west-1s3-website-sa-east-1s3-website-ap-southeast-2ap-northeast-1ap-southeast-1s3-us-west-2s3-eu-west-2me-south-1af-south-1eu-south-1ap-south-1us-west-2eu-west-2us-east-2s3-website-ap-southeast-1s3-1s3-globals3-ap-northeast-3eu-north-1airflowap-southeast-2s3-us-gov-east-1s3-fips-us-gov-east-1s3-me-south-1s3-ap-south-1ap-northeast-2s3-website-us-west-1ap-southeast-5s3-eu-north-1s3-ap-southeast-1s3-website-us-gov-west-1compute-1s3-eu-west-3us-gov-west-1s3-website-ap-northeast-1us-gov-east-1s3-fips-us-gov-west-1s3-website-us-east-1s3-ap-southeast-2ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1s3-us-east-2s3-ap-northeast-1authauthauth-fipsauth-fipseu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1rframeservicesbuilderstg-builderdev-builder*ociocpocsazuregcpawsdemoinstanceeu-west-3eu-south-2ap-southeast-3ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1previeweu-4us-4us-1eu-1us-2eu-2us-3eu-3appscomputepaasrag-cloudrag-cloud-chjcloudjcloud-ver-jpcdemonodebalancermembersipeuxvsoncillaocelotonzayalilynxsphinxfentigercustomercaracalo365cloudstaticxendevapp001testcode-builder-stgplatformmediasiteprojedrydpagesjsx0desazacncoitrueu4uhkukgrbrushatenadiarymyspreadshopfrom-flfrom-wvwebspace-hosttheworkpchatenablogcursorusercontentservesarcasmapplinzisakuratanwixsiteappchizigiizeis-into-carsdnsiskinkyadobeaemcloudis-a-therapistpgfogmyvncdojinis-an-actress1kappfldrvkozowqa2jpnmexprgmrfirewall-gatewaydynnscafjsfbsbxooguyfrom-gawoltlab-demois-a-anarchistwiardwebteaches-yogadattowebtb-hostinglive-websiteservegamegotpantheonfrom-nhsubsc-payfrom-ohvipsinaappfrom-cadyndns-officehomelinuxfrom-mahercules-appservebbsstreakusercontentfrom-okfrom-wyfastly-terrariumis-a-llamaqualyhqportalserveexchangeon-vaporvivenushopciscofreakgrayjayleaguesmetaaiusercontentfrom-iais-a-libertariansaves-the-whalestaveusercontentyolasiteoperaunitepoint2thisis-a-catererclaudeusercontentlinodeusercontentfrom-vagithubusercontentsells-for-lesshosteurcanva-appsplaystation-cloudddnsfreefrom-pafrom-prfrom-waddnskingoutsystemscloudhotelwithflightmydattois-a-nascarfanmydbserverminiserverdamnserverservehumouris-a-playerfrom-nvfrom-nmemergentagentgentappsamplifyappfrom-kyis-an-accountantnfshostserveircfrom-akpythonanywherestackhero-networkpostman-echolikescandydyndns-mailobservableusercontentserveftpfreeboxosfrom-utcdn77-storageamazonawsneat-urldyndns-serverlinodeis-a-teacherfrom-vtgleezemythic-beastsus1-pleniteu1-plenitla1-plenitpaywhirlservecounterstrikejdevcloudhealth-carereformis-into-animegoogleapisis-a-painterafricaisa-hockeynutatmetais-an-actora2hostedis-a-democratdatadetectest-le-patrondigitaloceanspacesis-a-designeris-a-hunterlinodeobjectstemp-dnsissmarterthanyoufrom-arsimplesiteevennodetownnews-stagingis-a-liberalgooglecodejelasticservemp3qualyhqpartnerdyndns-free1cooldnsest-a-la-masiondrayddnsdynuddnsfrom-orfrom-miis-a-bloggerfrom-himydobisscanvacodeis-an-engineerest-a-la-maisonupsunappdevinappswafflecellmyasustorwpenginepoweredfrom-ctservep2psame-appmyshopblocksthingdustdatalikes-piediscordsezis-with-thebandlpusercontentis-leetshopitsite3utilitiesis-a-personaltrainersinaappladeskis-a-cheflogoipselfipbase44-sandboxnospamproxyalibabacloudcsmesswithdnsauthgearappsiamallamawithgooglelutrausercontentmochausercontentframercanvasmytabitdyndns-homew-credentialless-staticblitzcpserverdiscordsaysis-a-nurseappspotatlassian-isolated-3premotewdfrom-mtwixstudiocode0emm180rmyactivedirectoryawsappsmytuleapdnsabrpolyspaceqbuserrenderbuiltwithdarkboutirgotdnsabrdnsdopaascanva-hosted-embedawsglobalacceleratorhomesecuritypcmyiphostditchyouripclever-clouddyndns-ipon-aptibleis-a-musicianhosted-by-filessecuritytacticsappspaceusercontenthomeunixstrapiappsame-previewcf-ipfsmycloudnaselasticbeanstalkis-certifieddontexistkasserverik-serverdrive-platformatlassian-3pfirebaseappherokuappawsapprunnerbarsycenteris-a-cubicle-slaveservehttpmyshopifyis-a-guruquicksytessiiitesorsitesmagicpatternsappis-a-cpameteorappfrom-wiis-a-rockstarbumbleshrimpdattolocaldatabricksappsreadthedocs-hostedfrom-rifamilydsdyndns-picsplesknsbplaceddnsaliasdynaliasdyndns-remotedoomdnsip-ddnsblogdnsis-a-doctorroutingthecloudamazoncognitobarsyonlinedsmynasddnsgurucloudflare-ipfsdeus-canvasfrom-idsmushcdnpagespeedmobilizerdyndns-at-homeunusualpersonhosted-by-previderis-a-republicandyn-o-saurstreamlitappworkisboringonthewificprapidqualifioappis-uberleetis-slickgetmyipwpdevcloudtypeformdyndns-at-workgentlentapismynascloudw-corp-staticblitzfrom-ingeekgalaxyservebeerfrom-mdonrenderspace-to-rentaivencloudappspacehostedwafaicloudcodespotblogspotatlassian-3p-us-gov-modfrom-ndfrom-msis-a-techieis-a-studentcustomer-ociis-a-photographerdurumisfrom-ksmassivegriddyndns-wikiis-an-entertaineris-a-hard-workermysecuritycamerafrom-mnrackmazedyndns-blogis-a-bulls-fanwritesthisblogfreemyipsimple-urlfrom-sdreservdauthgear-stagingest-mon-blogueuris-into-gamesrice-labsxtooldevicesakurawebis-an-anarchistoraclecloudappsdyndns-worksells-for-urhcloudfrom-dcfastvps-serverwpmucdnis-a-geekscrysecfrom-txis-into-cartoonsmodelscapetrycloudflarelocaltonetstreak-linkbalena-devicesfrom-njforgeblocksfreebox-oswebadorsitefrom-ncdoesntexisthobby-sitestreaklinkshomesecuritymacownprovidertuleap-partnersdattorelaywphostedmailservequakeis-a-socialistservehalflifepivohostingdynuhostingquipelementsw-staticblitzdyndns-webfrom-deproject-studyaliases121is-not-certifiedhercules-devis-a-financialadvisorservepicsis-a-greenloseyouripfrom-ilwithyoutubemwcloudnonprodwiredbladehostingdnsdojofrom-tnpixolinomyqnapcloudis-an-artisthostedpiis-a-landscaperauiusercontentoaiusercontenton-forgeis-a-conservativedreamhostersnet-freaksapps-1and1is-goneencoreapifastly-edgefrom-nesalesforcefrom-scdeployagentoraclegovcloudappsfrom-alis-a-lawyercechirevultrobjectsstufftoreadisa-geekddnsgeeklovableprojecttry-snowplowfrom-moblogsyteis-a-bookkeepernogmyforumravendbmyboxdeelementoredsaacficogoorinforgcomgobnatneteduidstoreorgcomnetintedudevnomepublorgcomneteduathgovtestscalculatorspaynowinfoquizzesresearchedcloudnsfunnelsassessmentsjscaleforcetmacltdorgmilcompronetgovbizpresseklogesrsccloudcustomfltusrcloude4corealmgovmunicontentproxy9metacentrumdyndyndyndnsdynpagespages-researchitionoccustomercomymyspreadshopipv64diskussionsbereich4limacomrub2ixfirewall-gatewayddnssspdnsbarsykeymachinesquare7myhome-serverspeedpartnercommunity-proschuldockxenonconnectgünstigliefernbwcloud-os-instancedyndnssecmy-routerxn--gnstigliefern-wobin-butterl-o-g-i-nisteingeekin-dslin-berlinin-brbfuettertdasnetzleitungsenin-vpnlcube-serverdyn-ip24logoipdyn-berlinruhr-uni-bochum12hpgoipsrvdnsfruskygit-repossvn-reposinternet-dnsgünstigbestellenhome-webserverxn--gnstigbestellen-zvbbplacedheimdnscosidnswebspaceconfiglima-citydyndns1istmeinvirtualuserschulplattformmy-gatewayddnsseclebtimnetztest-iservmein-iservvirtual-userhome64iservschuletaifun-dnstraeumtgeradeschulserverdynamisches-dns123webseitednshomehs-heilbronndnsupdaterbssgraphicdwadpdwdaepeweaawapaafpfwfabwbpbacwcpcciwebuserapiobjectsidsiskospockkimodorikerbonesteamsparisjanewaypicardglobaltarpitreedpikekiraworfsulukirkarchertuckerhackercanarywesleystagingprereleaset3r2lpbravepanelngrokiservstglclcrmerpflypagesbarsyvivenushoplocalcertlocalplayerbearbloggatewaydeno-stagingis-not-ais-a-goodbotdashvercelmocha-sandboxplatter-appreplitgithubpreviewworkersinbrowserevervaultis-ahrsndenoxmitmodxmyaddrstorageapipayloadgrebedocruncontainersstgstagelclstageloginlineis-a-fullstackcodepenleapcellngrok-freeis-coolstoragewebharemediatechlibp2pdiscourseimaginecomyspreadshopstoreregbiz123hjemmesidefirmcoorgcomnetedugovsldorgmilcomwebgobartnetedugovtmorgpolcomsocartnetedugovassoagrondiscoodontk12medcuegyecpaabgengorgmilgalsaltulcomadmesmgobpubdocmonfindgnriouioproartlatvetnetfotedulojgovntrturibrbarxxxofficialbasechefprofmktgpsictechinfoarqtcontdentrrpppsiqgit-pagesritmedfieorgcomlibprieduaipgovriikmeactvsportorgmilcomscieunnetedugovnameinfopintouchtawktotawkmyspreadshoporgcomnomgobedu123miwebcomputeorgcomnetedugovbiznameinfocognito-idpeusc-de-east-1onjelasticnxaspdnsbarsydirectwpdeuxfleurstransurldogadoprvwcloudnsamazonwebservicesdnshomeuserpartycokoobinmkmfidymyspreadshopalandkapsiikixn--hkkinen-5wacloudplatformhäkkinen123kotisivuidacorgmilcompronetedugovbiznameinforadioorgcomneteduuserexperts-comptablestmmyspreadshopgretaprdcomnomynhccifbxoshuissier-justicenotairesaeroportfreeboxoson-webavocatassoportgouvkdnschirurgiens-dentistes-en-franceavouesfbx-os123sitewebveterinairechirurgiens-dentistespharmacienchambagrimedecinfreebox-osdediboxgoupilemszicpyicpvicppleysheezypagesedugovcnpyorgcomcybllcpvtnetedugovtnxonlineschooldaemond6atcopanelorgnetplybotdashstackitkaasorgmilcomnetedugovbizmodltdorgcomedugovcoorgcomneteduappwriteacorgcomnetedugovcloudtranslateusercontentorgcomnetedumobiassoorgcomnetedugovbarsysimplesitediscourseindorgmilcomgobneteduorgcomwebnetedugovguaminfonxhra教育敎育網絡网絡组織組織网络網络组织組织公司政府個人个人箇人ltdorgcomincneteduidvgovxn--uc0ay4axn--55qx5dxn--mk0axixn--io0a7ixn--uc0atvxn--zf0avxxn--lcvr32dxn--od0algxn--wcvs22dxn--gmqw5axn--od0aq3bxn--mxtq1mxn--ciqpnxn--tn0agxn--gmq050iorgmilcomgobneteduiservwp2tempurlmircloudfreesitewpmudevmyfastgadgetcloudaccessjelehalfboltfastvpsemergenteasypanelopencraftizcombrendlynamefromrtpersoadultmedorgpolrelcomproartnetedufirminfoassoshopcoopgouvtmcomediahotelforumvideosportorgsexagrargameslakaseroticaerotikatozsdereklamcasino2000filmsuliinfoboltshopprivnewsszexcityutazasjogaszkonyveloingatlaneacaicogoormyᬩᬮᬶmilwebschnetkopbizzonedesaponpesxn--9tfkymyspreadshopgovmytabittabitorderravpageaccok12idforgnetgovmuniltdplcaccotttvorgcomnetmeca6g5gpgamubacaicniocoukuptverdruscsdelhiindorgmilcomwebnicfingenpronetintedugovresbizbiharbarsyinternetbusinessschooltravelsupabasealumnigujaratfirminfoaeropostbankcoopindevscloudnsno-ipbarsybarrell-of-knowledgebarrel-of-knowledgensupdategroks-thisdnsupdatefor-ourknowsitalldvrcammittwalddynamic-dnsv-infowebhopselfipdyndnshere-for-moreilovecollegemayfirstforumzcloudnsmittwaldservertypo3servergroks-theeusekd1cdndyndnsidrawsainaueuapjpusstagemocksysdevicesclientcustreservdcustdevdisrecprodtestingcobeebyteutwenteboxfusebravepstmndedynngrokorgmilcomnomnetedugovqcxqzzbarsythingdustmo-siemensrb-hostingfh-muenstergitbookbluebitecloudbeesusercontentnodeartkiloappsforgerockdarklangresinstagingapigeebubbleb-datascryptedhypernodedappnodepantheonsitegitlabgithubkeeneticvirtualservercleverappshostyhostingon-rioedugitticketstelebitwixstudioon-k3sicp0icp12038jeleqotolairbubbleappsmyaddrstolosmyrdbxwebflowdrive-platformbeagleboardhasura-applolipopdefinimavaporcloudmusicianwebflowtestazurecontainerresindevicereadthedocsloginlineeditorxmoonscalesandcatsbasicserverwebthingsbrowsersafetymarkbeebyteappbitbucketidaccovistablogorgschnetgovxn--mgba3a4f16axn--mgba3a4fraarvanedgeايرانایرانjclaspeziapdudcefegelemeperetevebacanatavaparasabgagfgogrgpgalclblimfmrmcbmbvbfclcmcvcrcpcchlimifibicivipirisimncnbnanenrnpntnnolomobocoaogorosopotoptvtatctbtmtltotpusulunutpspapaqsvpvvvtvavvrtrsrprgrfrcrbrarorkrvstsssbscsmsispzczbzbozen-suedtirolmyspreadshopxn--bulsan-sdtirol-nsbxn--valledaoste-ebbtrentinoaltoadigetrentin-sued-tirolxn--forlcesena-c8axn--forl-cesena-fcbxn--bozen-sdtirol-2obtriestetrentinsuedtiroltrentino-s-tirollecceudineaostesienaparmaluccapaviagenoapaduaaostamonzaabruzzoternirietiturinmilanbozenlaziofermoleccocuneonuoropratola-speziavdataaligfvgpugmolcalcamlomumbsicpmnvenvaoedugovabrsarmaremrbastoslazibxosfirenzetrentinosüdtirolval-d-aostavalle-aostamessinacremonaravennatoscanatrentin-suedtirolbolognacalabriaurbinopesarofriuli-v-giuliaogliastraxn--valle-aoste-ebblaquilaandriatranibarlettasyncloudxn--valle-d-aoste-ehbaostavalleyvalled-aostatrentino-alto-adigevallee-d-aostexn--balsan-sdtirol-nsbpistoiasicilialucaniacataniaiserniaperugiabresciaveneziagorizialiguriaimperiabulsan-suedtirolbalsan-suedtirolbarlettatraniandriaxn--trentino-sdtirol-szbforlì-cesenatuscanyvallée-d-aostemantovavallée-aostecasertapiemontevalleaostaval-daostafriulivgiuliatrevisoforli-cesenavalléedaosteferrarapescaravald-aostatrentino-altoadigefriuli-vegiuliavallee-aostecarboniaiglesiastarantomediocampidanovalleedaostetrentinosud-tirolcampobassotrentinsüd-tiroltrentinosüd-tirolmonzabrianzatrentino-südtirolxn--trentino-sd-tirol-c3bpotenzacosenzavicenzaemiliaromagnavenicefrosinonemarchepordenonetrentinosued-tirolvaresemolisevalléeaostefriuli-veneziagiuliabasilicatalatinaanconasavonaveronamodenabiellabolzano-altoadigepugliafoggiaumbriatrentino-stirolgenovapadovamateranovararagusapiacenzatrentinostirolvalleeaostetempio-olbiasudsardegnatrentinsudtirolmassa-carrarafriuliveneziagiuliatrentinosuedtirolandria-barletta-tranitrapanixn--cesenaforl-i8amaceratacaltanissettaascoli-picenobrindisicarraramassacagliaririmininapolivibo-valentiachietibulsan-sudtirolbalsan-sudtiroltrentino-a-adigebulsanbalsaniglesiascarboniamilanotorinoteramodell-ogliastraarezzotrentinoalto-adigerovigotrentovenetoiglesias-carboniatrentino-sud-tirolaltoadigereggio-emiliareggio-calabriasardegnatranibarlettaandriapiedmontxn--sdtirol-n2amedio-campidanotrentino-süd-tirolfriuli-vgiuliafriuli-ve-giuliaromeennaromapisa32-b16-b64-blodiastibarineencomonaplesforlicesenailiadboxosalessandriasicilytrani-barletta-andriaxn--trentin-sdtirol-7vbpesarourbinotrentinsued-tirolcesena-forliforlìcesenaemilia-romagnamonzaebrianzaxn--trentinsdtirol-nsbtrentinos-tiroltrentinsüdtirolvalledaostaolbia-tempiocampidanomediovibovalentiasassarivalle-daostalombardysud-sardegnafriulivegiuliareggioemiliamonzaedellabrianzaalto-adigevercellitrentin-sudtiroltraniandriabarlettatrentino-sudtirolascolipicenobozen-südtirolfriulive-giuliaflorencexn--cesena-forl-mcbcarbonia-iglesiasaosta-valleycarrara-massadellogliastratrentinoa-adigexn--valleaoste-e7apesaro-urbinoxn--trentinosdtirol-7vbxn--trentin-sd-tirol-rzbxn--trentinsd-tirol-6vbtrani-andria-barlettatrentin-süd-tirolxn--trentinosd-tirol-rzbgrossetomonza-e-della-brianzasüdtirolreggiocalabriatrentinoaadigetrentin-südtirolverbano-cusio-ossolafriuliv-giuliaverbaniacampaniatrentino-aadigefriulivenezia-giuliasardiniaandriabarlettatranibarletta-trani-andriacatanzarooristanourbino-pesarocesena-forlìvalle-d-aostacampidano-medio123homepagesiracusatempioolbiasuedtirollombardiaavellinocesenaforlìtrentinofriuli-venezia-giuliabozen-sudtirolandria-trani-barlettabulsan-südtirolbalsan-südtirolmonza-brianzabolzanotrentino-sued-tirolbellunosalernolivornocrotonesondriodnshometrentinsud-tirolmassacarraratrentin-sud-tiroltrentino-suedtirolviterbobergamocesenaforliolbiatempiopalermobeneventoagrigentoofcoorgnetfmaitvphdengorgmilcomschnetedugovperagrikanieasukehandachitatokaiaisaikonanoharuamaobuhigashiuraowariasahiinuyamatobishimaiwakurashitarainazawatoyonegamagorimihamatoyotataharakariyayatomioguchikomakimiyoshinishiotokonamekiyosuchiryutoyohashiokazakiisshikikasugaikotakiratoeianjotogofusosetohazutsushimashinshirotakahamanisshinshikatsuhekinantoyokawaichinomiyatoyoakeodateogataakitaikawakyowahonjoogayurihonjonoshirokamiokakatagamimitanegojomeyokotekosakadaisenkazunonikahohonjyomoriyoshimisatohappoukamikoanihachirogatahigashinarusesembokufujisatokitaakitaitayanagiowanitakkomutsutsurutahirosakigonoheoirasetowadamisawanohejiaomorishingohiranairokunohehashikamitsugarushichinohehachinohenakadomarisannohekuroishisakaeisumiasahiotakiinzaiabikomatsudoyachiyomutsuzawakujukuriomigawakashiwatoganemihamanaritasakuranagaramobarahanamigawachoshishiroichoseikozakishisuikatorimidorichonankyonanfuttsuonjukufunabashinagareyamanodasosatakochuotohnoshourayasukimitsuyokaichibayotsukaidosodegauratateyamakamagayayokoshibahikariyachimatakatsuuratomisatokisarazukamogawaichikawanarashinoichinomiyashimofusaminamibososhirakoichiharaoamishirasatoikatahonaiainansaijoseiyoiyoozuuwajimaniihamanamikatamasakiuchikokihokutobetoonshikokuchuomatsuyamaimabarikamijimakumakogenyawatahamamatsunosabaeikedaobamasakaifukuiohionotsurugamihamawakasaminamiechizeneiheijikatsuyamatakahamaechizensoedaukihaomutaokawanishiogoribuzenonojosueumiokiotochikugosasagurisaigawamizumakishinyoshitomikurumekurateyamadakasuganakamamiyamanogatatakatahakataiizukakawaratagawakasuyaashiyainatsukimunakataminamitsuikishonaikurogifukuchikeisenhigashimiyakoshinguyukuhashiokagakiyamekogaongausuikahotohochuotoyotsumiyawakadazaifuhisayamatachiaraiyanagawanakagawahirokawachikujochikushinochikuhochikuzennamieotamaokumashowateneiiwakikoorinangoononishigoshimogoomotegomishimafukushimaasakawakagamiishishirakawaiitatefutabahiratayugawahanawakitakatakawamatakunimiyabukibandaihigashihironoyamatomiharuyamatsuriaizubangedatesomaaizuwakamatsuyanaizuaizumisatonishiaizuizumizakikitashiobarataishinkaneyamakoriyamainawashirotanagurafurudonosamegawasukagawaishikawatamakawaikedaogakitaruiginanenahashimahichisonakatsugawaibigawashirakawamizunamiminokamomitakekawauesekigaharatomikasakahogikitagatayamagatatajimianpachimotosuyaotsukakamigaharahidakanisekitokigujominogodoyorogifukasamatsutakayamawanouchihigashishirakawakasaharashimonitatsumagoichiyodakannakanrashowameiwakiryuotaoratomiokafujiokaitakuranaganoharahigashiagatsumatakasakishibukawaminakamikatashinatsukiyonokawabanumataannakaoizumimidorishintoisesakiuenoyoshiokakusatsutakayamanakanojonanmokutamamuratatebayashimaebashiotakekaitadaiwahongofuchukuietajimashobaramiharahatsukaichihigashihiroshimamiyoshikumanokurenakasakaseraseranishiasaminamifukuyamashinichionomichiosakikamijimajinsekikogentakeharaotobenanaeikedatohmaozoraobiraabirakyowaeniwataikibibaisharirebunerimohiroooketootarupippunishiokoppechitosefurubirahakodateshiranukakitahiroshimakushiroobihironanporoiwamizawaniikappukunneppufukushimanakasatsunaitoyourakuromatsunaiakabirakamisunagawashibechaurakawakamifuranonakatombetsuasahikawashimokawakayabeokoppebiratoriabashirisaromaatsumanumatahidakabifukamukawamikasahorokanaitoyotomisarufutsuhigashikawaishikarikitamiyoichiesashiiwanaitomariminamifuranoakkeshifuranotoyakoyakumootoineppushikaoishiraoinemuronayorohaboroashorobihororishirifujiutashinaihokutotakasuebetsuurausuassabukikonaishimamakinaiedatetoyabieinikiesanuryuoumuteshikagarikubetsuashibetsukimobetsuaibetsutobetsusobetsuembetsushimizuchippubetsurishirihokuryuhoronobeshintokutsubetsushibetsuhonbetsumombetsutsukigatakuriyamakoshimizushiriuchikutchanmurorannoboribetsukamishihorowassamushinshinotsukembuchiwakkanaikamoenaikiyosatotakinoueshikabesunagawafukagawanakagawatakikawakamikawahigashikagurahamatonbetsumatsumaemoseushirankoshishakotanimakanemashikeotofuketomakomaisandatambaitamiawajikasaiasagoshisoonoakoyashirotoyookaminamiawajiinagawafukusakitakasagokamigorikasugaharimayokawaashiyahimejiakashitaishiaogakisannantakinosumototakarazukanishinomiyashingugoshikinishiwakiyokatakaaioimikisayoyabukawanishiamagasakisasayamashinonsenkakogawaichikawakamikawatatsunotsukubaiwamaogawaasahisakaitokaioaraiitakobandodaigosuifuinaamikasumigaurakashimaomitamayachiyoshimodatetomobetoridehitachinakainashikisakuragawakasamayawaramoriyahitachiomiyanamegatayamagatahitachikamisuushikutakahagiibarakitonekoganakasowayukimihojosomitoryugasakishimotsumafujishirotsuchiurachikuseihitachiotashirosatotamatsukuriuchiharashikahakuinanaotsubatawajimakahokukawakitatsurugikaganominotosuzuuchinadakomatsuanamizunakanotohakusannonoichikanazawaiwateshiwafudaikawaimoriokaofunatohanamakikuzumakikitakamininohekunoheyamadayahabasumitaichinosekitanohatahiraizumirikuzentakatajobojiotsuchihironomiyakoiwaizumikarumaiichinohenodakujitonooshushizukuishifujisawamizusawakamaishikanegasakimannoutazukotohiraayagawazentsujihigashikagawauchinomikanonjisanukimarugamemitoyotakamatsutadotsunaoshimatonoshoakuneamamiizumihiokiyusuikinkoisasookouyamanakatanekagoshimakanoyaisenkawanabeminamitanemakurazakitarumizunishinoomotematsumotosatsumasendaioimatsudaayaseebinamiurazushinakaiodawaraiseharasagamiharahakoneaikawakaiseiatsugitsukuihadanoyamatoyamakitazamaoisochigasakininomiyayokosukakamakuraminamiashigarafujisawasamukawakiyokawahiratsukayugawaraokawaumajikochitsunootoyoakiinonishitosayasudahidakamiharasakawaniyodogawahigashitsunokagamigeiseisusakiotsukinaharisukumomurototosakamiochitoyotosashimizumotoyamanankokunakamurakitagawayusuharaogunichoyoukiasoutoozugyokutoamakusamifunetakamoriyamagaminamataminamiogunikikuchisumotoyamatonagasumashikiaraokumamotokamiamakusanishiharayatsushiroayabeseikasakyoideineujinakagyokameokakyotangokyotanabekyotambaminamiyamashiroyamashinatanabeyawatawazukaminaminantanmiyazuhigashiyamafukuchiyamakitamukokamojoyokizumaizuruujitawaraoyamazakinagaokakyokumiyamakawagoeinabeshimameiwaasahitaikiudonoisetsukisosakikuwanamihamamiyamasuzukatamakimisuginabarikumanokomonominamiisewataraitobakiwatakikihotadomatsusakayokkaichikameyamaureshinoishinomakishichikashukuohirataiwaosakizaohigashimatsushimashikamaiwanumashibataogawaraonagawakawasakiseminemarumoriminamisanrikukakudamuratawakuyatomiyanatoriwataritagajomisatotomekamirifushiroishimatsushimayamamotoshiogamafurukawahyugaebinotsunosaitoayakushimanobeokakitauramiyazakitakazakigokaseshiibamimatashintomikunitomikitakatakobayashikawaminamitakaharukijotakanabemiyakonojonishimeranichinankitagawakadogawamorotsukakisofukushimaminamimakisakaeobuseikedaogawamiasaokayaasahiotakiotarichinoinaomichikumakomaganechikuhokukaruizawayasuokaooshikaikusakaminamiaikitogakushimatsukawakawakamitateshinatakamorikitaaikishiojirimiyadahakubaiizunaiijimaiiyamamiyotasuzakayasakatoguraookuwanagawaminowahirayayamagataminamiminowafujimiomachisakakitakaginaganonakanosakuhokomoronagisoshinanomachiwadauedaiidaharasuwatomiachiaokianankisosakunozawaonsenagematsutakayamashimosuwamatsumotoyamanouchinakagawamochizukiazuminotatsunoobamaomuraseihiunzenosetofutsuikichijiwanagasakiisahayahasamisaikaikawatanasasebohiradokuchinotsugototogitsutsushimashimabarashinkamigotomatsuurayamazoekashibaikomakawaitenrioyodosangokoryoudaojiikarugayamatokoriyamatenkawakatsuragikurotakikawakamimiyakemitsuetakatorikamikitayamayamatotakadahegurishinjokanmakisakuraitawaramotogoseoudanarasoniandokawanishishimoichihigashiyoshinokashiharashimokitayamanosegawayoshinomintsivorytopazsakuragehirnsumomoaseinetopalmail-boxmokurenyoitamuikaojiyagosensanjoaganomyokoseiroagaomishibataniigatanagaokamurakamiuonumayuzawakariwatagamitainaitsunanminamiuonumatochioyahikojoetsuseiroukamosadoizumozakitokamachiitoigawasekikawakashiwazakitsubamemitsukekokonoesaikiusukibeppuusahimeshimakunisakihasamataketatsukumihitaoitahijikusuyufukujukamitsuebungoonobungotakadaibaraniimibizentsuyamaokayamakasaokahayashimayakagemaniwaakaiwamisakishinjotamanotakahashikibichuowakesojanagishookumenannishiawakurakurashikiasakuchisetouchikagaminosatoshotomigusukunakagusukuyaeseizenaurumaiheyaaguniogiminanjokinminamidaitokitanakagusukuyonaguniokinawaishigakikunigamiurasoekadenataramahiraraginozataketomishimojizamamitonakiitomanhigashimotobuyonabarugushikamionnanahanagohaebarukumejimakitadaitonakijinnishiharayomitanginowantokashikiishikawaikedasuitaminohizuminishisakaikananabenodaitoosakasayamayaokishiwadatadaokakaizukatondabayashichihayaakasakakumatorikadomasayamahigashiosakashijonawatehirakatataishimisakitajirihannansennankatanotoyonominatosettsuhigashiyodogawaibarakinosekitachuohigashisumiyoshifujiiderakashiwaraizumiotsutoyonakamatsubaramoriguchiizumisanoshimamototakatsukineyagawahabikinotakaishikawachinaganoyoshinogarikamiminearitaouchiimarihizenogikashimaariakekiyamafukudomikitagatakitahataomachigenkaikanzakinishiaritakyuragisagataratosutakushiroishikaratsuhamatamakouhokukawagoeyoshidasatteogoseirumaasakaurawaogawaniizaomiyayoriiotakishikihonjooganohannohanyuinasaitamaokegawaarakawayoshikawayokozehasudasayamahidakafukayachichibuiwatsukiryokamiyoshimikamiizumifujimiwarabiranzanmiyoshiminanoyashiosakadosugitomisatohigashichichibutodasokakukiyonokazoshiraokakasukabekounosukawajimatsurugashimamiyashirokitamotohatoyamamoroyamahatogayakumagayakawaguchinagatorokamisatomatsubushinamegawatokigawakamikawafujiminohigashimatsuyamakoshigayatokorozawas3isk01isk02ryuohkoseikonanaishorittotakashimamaibarahikonetorahimenishiazaikokagamokotoyasuotsukusatsunagahamamoriyamatoyosatotakatsukinotogawaomihachimanhigashiomiakagiunnanizumogotsuamayatsukakakinokimatsuehamadamasudahikawahikimiokuizumoyasugiyakumomisatotamayuohdahigashiizumookinoshimanishinoshimatsuwanoshimaneshimadafujiedayoshidashimodagotembaiwataatamikosaiyaizuitoizumishimahaibaramakinoharaomaezakikawanehonkannamisusonohigashiizufukuroinumazukawazufujiaraishizuokahamamatsushimizuizunokunimatsuzakimorimachiminamiizunishiizukikugawakakegawafujikawafujinomiyaujiietsugaoyamayaitaohiranikkoashikagakuroisokanumasakurashioyakarasuyamamotegiichikaikaminokawatochigihagamokanogisanobatonasumibunasushiobaranishikatautsunomiyaiwafunemashikoshimotsukeohtawaratakanezawaitanokomatsushimatokushimaichibaminamiaizumiwajikikainanmiyoshinarutomimamugiananmatsushigesanagochishishikuinakagawamachidachiyodakomaefussainagitaitochofufuchuomeotahigashiyamatotoshimaokutamaaogashimakodairaedogawaarakawahachiojishinagawatachikawashibuyasuginamihinodekiyosesumidaoshimanerimamitakahamuraadachinakanomizuhobunkyomegurominatokoganeihigashikurumekokubunjihigashimurayamamusashimurayamatamakitahinochuokotokatsushikakouzushimaogasawaraakishimakunitachishinjukusetagayamusashinohachijoitabashiakirunohinoharachizunanbukotouramisasawakasayonagokogehinoyazutottorinichinansakaiminatokawaharaoyabetairainamiasahinantoimizufuchutakaokakurobeyamadajohanatoyamatonaminyuzenfunahashinakaniikawanamerikawaunazukitogahimiuozufukumitsutateyamakamiichiiwadearidayuasainamitaijikatsuragiaridagawatanabemihamahidakakainankiminomisatoshingushirahamakamitondayurakozakoyagobokitayamawakayamakudoyamahashimotokushimotokozagawahirogawakinokawanachikatsuurarsuseroeoishidasagaeoguniasahinagaitendonanyoobanazawanishikawasakataohkuratozawamikawamamurogawayamagatafunagatatakahatashonaishinjokahokuiideyuzakawanishitsuruokakaminoyamayamanobeshiratakamurayamanakayamakaneyamahigashineyonezawasakegawamitouubeyuuabushimonosekitabuseoshimatoyotaiwakunihikarishunannagatohagihofukudamatsutokuyamashowadoshitsurunanbukoshukaiminami-alpsnirasakikosugeotsukioshinohokutominobuyamanashifuefukichuokofuichikawamisatoyamanakakonakamichitabayamanishikatsuranarusawafujikawahayakawafujiyoshidafujikawaguchikouenohara長野京都岐阜大阪三重群馬千葉滋賀佐賀奈良adednelgaccogogror秋田愛知高知埼玉沖縄栃木熊本岩手青森山梨新潟島根鳥取長崎香川宮城石川大分宮崎茨城山口兵庫山形徳島広島福島福岡岡山富山静岡愛媛福井東京xn--4it168dhatenadiaryxn--vgu402ckawaiishophatenablogcocottenamaste北海道penneehimeiwateversestabachibashigagonnagunmapermahaccaakitaosakauh-ohblushkochiaichifukuikuroncapooitigohyogotokyokyotopunyuthickcheap0t00g00j0mie2-ddaapyawjg0amfemsubxiiboomoobutchueekpgwrgrherskrboyrdyupperunderflierchipsmydnsheavyangryhippygirlyrulez神奈川鹿児島和歌山bambinaxn--nit225kokayamasaitamaxn--k7yn95exn--1lqs03nsapporoparasitelolipopmcxn--efvn9sniigatafukuokatokushimafukushimahiroshimakagoshimafakefurokinawaxn--8pvr4ucoolblogxn--0trq7p7nnkawasakinagasakimiyazakichilloutxn--8ltr62kxn--klty5xpeeweezombiecutegirlxn--rny31hxn--uuwu58axn--ntso0iqx3axn--djrs72d6uytoyamanikitanyantakagawamimozanagoyaboyfriendxn--2m4a15egreaterchowderegoismyamagatafashionstorexn--elqq16hxn--pssu33lsendaimiyagixn--rht27zpecoriaomorisaloonwatsonvivianxn--djty4knobushipigboatnaganopinokoxn--f6qx53asadistvelvetsecretxn--5js045dchicappayamanashiibarakidigickgirlfriendxn--1lqs71dmongolianxn--c3s14mxn--qqqt11mtochigixn--5rtq34kparallelo0o0mondkobesagabonadecaoitanarafoolkilldecimainhiholomosblokilociaoundopupugifutankcrapflopnooroopsmodsholyjeezstripperpepperbittershizuokaxn--rht3dkitakyushureadymadeicurusversusmatrixxn--rht61ehungryfloppygloomycrankyhandcraftedlittlestarxn--klt787dxn--kltx9awhitesnowsunnydaytottorilovepoptheshopbuyshopxn--5rtp49cxn--d5qv7z876cwebaccelxn--kbrq7oxn--4pvxsxn--1ctwolovesickkumamotocatfoodxn--tor131oyokohamawakayamatonkotsuxn--ehqz56nxn--uist22hxn--6btw5axn--kltp7dyamaguchifrenchkisspussycatxn--4it797kxn--uisz3gbabybluexn--zbx025dnetgamersxn--7t0a264ckanagawaxn--6orx2rishikawaxn--ntsq17ghalfmoonschoolbusjellybeanxn--mkru45iusercontentlolitapunkxn--32vp30hsakurastoragehokkaidoshimanecandypopbabymilksupersaleweblikeraindropbackdropwebsozaikikirarahateblodaynightmeneacsccogoormobiinfoaeusxxorgmilcomnetedugovorgcomnetedugovbizinfotmprdorgmilcomnomedugovassnotairespresseassocoopgouvveterinairemedecinpharmaciensorgnetedugovtraorgcomedurepgovmeneperekgacscaiiocogoitoresmshsseoulbusanulsandaeguc01milvkimmvchungnamjeonnamjeonbukeliv-dnsgyeonggijejueliv-cdnincheondaejeongangwongyeongbukgwangjuchungbukgyeongnameliv-apicoeduindorgcomembnetedugovorgmilcomnetedugovjcloudorgcomnetintedugovperbnrinfocooyorgcomnetedugovethipfscanvamypepethw3sstorachakeeneticjoinmcinbrowserdwebcyonnftstoragemyfritzaemewphlxachotelltdorgcomwebsocschngonetintedugrpgovassnomgacsccoorgnetedugovbizinfo123websiteidorgmilcomasnnetedugovconfidmedorgcomplcschnetedugovaccoorgnetgovpresstmassoirseproxaccosoundcasthoptocraftvp4c66orgnetedugovitsmcdirmyboxbarsyedgestacksynologylogintoopencloudnohostwebhopdiskstationi234tcp4hoocgroknoipprivmydsddnsdnsforlohmustransipdscloudfilegear-sgbrasiliafilegearframerbarsybarsyonlinecoprdorgmilcomnomedugovinforgcomnetedugovnameacprorgcomartnetedugovpresseinfoassoinstgouvorgnycedugovbarsydscloudjuorgcomnetedugovminisiteaccoororgcomnetgovorgmilcompronetintedugovbizmuseumnameinfoaerocoopaccoorgcomnetintedugovbizcooporgcomgobneteduorgmilcomnetedugovbiznameaccoorgmilneteduadvgovcoorgcomnetaltgovforgotherhiskeeneticispmanagernomassoprod5476132eastasiacentraluswesteuropewestus2eastus2pnortheurope-01newzealandnorth-01southindia-01southcentralus2-01norwaywest-01eastus2-01westus2-01australiaeast-01italynorth-01israelnorthwest-01swedencentral-01westeurope-01centraluseuap-01taiwannorthwest-01uaecentral-01northcentralusstage-01israelcentral-01mexicocentral-01canadacentral-01austriaeast-01germanywestcentral-01francecentral-01ukwest-01denmarkeast-01polandcentral-01eastus-01westus-01swedensouth-01eastus3-01westus3-01brazilsouth-01centralus-01francesouth-01australiacentral-01westindia-01uaenorth-01jioindiacentral-01canadaeast-01belgiumcentral-01spaincentral-01koreacentral-01chilecentral-01qatarcentral-01westcentralus-01eastus2euap-01norwayeast-01southafricanorth-01brazilsoutheast-01germanynorth-01switzerlandnorth-01switzerlandwest-01japanwest-01southafricawest-01japaneast-01eastasia-01indiasouthcentral-01taiwannorth-01centralindia-01uksouth-01southcentralus-01northcentralus-01eastasiastage-01indonesiacentral-01australiacentral2-01australiasoutheast-01malaysiawest-01koreasouth-01southeastasia-01southeastus5-01northeastus5-01jioindiawest-01rucdnwest1-usfra1-desandboxjls-sto1jls-sto3jls-sto2aglobalabglobalsslmapprodfreetlsmapvpslon-1lon-2ny-1fr-1sg-1ny-2paassnwebpaashostingjelasticnordeste-idcsocuserpagescwebfileblobservicebuscoreatlricnjsjelasticwebsitestoragesezagbinruhuukjptsmyspreadshopmynetnameakamaiorigin-stagingfrom-coipv64dynv6cdn77serveblogadobeaemcloudhicamsprytdnsupno-ipownipde5ovhicpfirewall-gatewaysytesmypsxbarsyusgovcloudapimyamazemyradwebakamaihdsaveincloudfastlylbfrom-lasubsc-paysquare7in-the-bandblackbaudcdnhomelinuxoninfernoctfcloudservebbsdns-dynamiccloudfrontakamai-stagingipifonyham-radio-opsenseeringclickrisingcommunity-profrom-nylocalcertgrafana-devedgesuite-stagingcloudflareanycasteating-organicatlassian-devmydattofeste-iplocaltotorprojectknx-serveredgekeycloudflareglobalcloudyclustercasacamserveftpakamaized-stagingakamaiorigindns-cloudmyeffectboomlabotdashbuyshousestwmailhetemlazure-mobilein-dslthruhereredirectmedynuddnsbouncemesupabaseluyanicloudappakamaicloudfunctionsdebiannhlfanpgafanstatic-accessin-vpnmysynologymafeloappudohomeftptrafficmanagersiteleafseidatmemsetcloudflarecloudaccesskeyword-onazure-apiis-a-chefdoes-itgets-itwebhopselfiphomeipkicks-assedgesuitewindowsserver-ontunnelmolemydissentscrapper-sitecloudflarecnuni5srcfggffiobbzabchrsndenodynuopikddnsvpndnsakadnselastxkinghostvps-hostfastlyhomeunixazureedgeshopselectdontexistmyfritzcloudjiffyalwaysdatasells-itsquaresbroke-itazurefddattolocalat-band-campmeinforumfamilydsazurestaticappsdefinimabplaceddnsaliasdynaliasnow-dnsblogdnsroutingthecloudendofinternetdsmynasakamaiedgemymediapcadobeio-staticakamaiedge-stagingakamaihd-stagingddns-ipprivatizehealthinsurancelive-onkrellianschokokeksmassivegridmysecuritycamerarackmazeserveminecraftfrom-azis-a-geekakamaizedmoonscaleoffice-on-theusgovtrafficmanageradobeioruntimeedgekey-stagingreserve-onlinechannelsdvrdnsdojousgovcloudappcdn77-sslapps-1and1podzoneazurewebsitesdynathomescaleforceyandexcloudvusercontentisa-geekcdn-edgescoaemalcesappwriteazimuthtlonarvobuiltwithrocketnoticeablestorecomwebrecnetperotherfirminfoartslgdloncogoiltdorgmilcolcomplcschgenngonetedugovbiznamefirmmobiacincoorgmilcomnomwebgobnetintedubizinfocomyspreadshopdemongovtransurl123websitehosting-clusterkhplaycistrongsnesosvalervålerxn--vler-qoaossandeheroysandeherøybøboheroyherøyxn--hery-iraxn--b-5gavalerbøboxn--b-5gasandesandexn--hery-iraxn--vler-qoavålerhåreålaahavaofsfvfhlolnlalrlhmfmtmahcostntbuåstrmreigersundmyspreadshopgálsáeidsvolltingvollgildeskalflorøvadsøvardøvanylvenxn--bhccavuotna-k7astrandaxn--kvnangen-k0axn--sknland-fxaxn--mosjen-eyarakkestadhyllestadnannestadvevelstadvaapstenordre-landsondre-landsøndre-landtjieltexn--vrggt-xqadsør-aurdalsor-aurdalheradstordmoldefordeførdeseljefedjeryggehemnexn--krehamn-dxasognegranesøgnebrynetjomevallebykletokkegiskedovretjømehobølvoldasaudatolgasømnaviknadønnasomnadonnatranafrananesnaraumasmolatrænafrænalesjasmølaørstaorstahitrafloraaukraloppafrøyarissasnasahalsagalsaromsaraisaráisafroyasnåsagronghobolfjelltydalårdalardalaskimharamkraanghkekråanghkesorumbarumhurumbærumsørummodumsálátbálátfrognbjugnvåganvagangulenskienløtenlotenstrynvefsnxn--merker-kuaskaunsveiobømlobomloskjåkvardoflorovadsosalatbalatsálatklæbuklabuselbubarduulvikskjakklepprisørxn--nttery-byaeflåeidflahofmilgolholsellomskifetvikdepvgsfhsaskerrisorhamarasnesåsnesrørosrorosxn--slat-5namasoynaroyvaroyluroydyroyaskoyradoyandoyrodoymeloyradøyandøyrødøymeløyaskøylurøydyrøymåsøyværøynærøyhoylandethøylandetdivtasvuodnalørenskoglorenskognesoddtangenxn--tjme-hraxn--smla-hraxn--stjrdal-s1aunjargalillehammerunjárgaxn--hamary-fyadavvenjargaxn--bearalvhki-y4a123hjemmesidegjerdrumxn--brnnysund-m8acxn--tnsberg-q1axn--mlatvuopmi-s4axn--snsa-roaxn--skierv-utaxn--brum-voatysfjordkvafjordeidfjordkvæfjordsongdalenmjondalenmjøndalenxn--gls-elackragerogáŋgaviikagangaviikasørreisasorreisasør-varangersor-varangerxn--risr-iraskiervaxn--frna-woaxn--trna-woakvinesdalleksvikleirvikrøyrvikroyrviksvelvikvenneslaevje-og-hornnessandnessjøenmarnardalvindafjordsandefjordenebakksnillfjordullensvangxn--trany-yuabrønnøysundnamsskoganaustevollxn--stjrdalshalsen-sqbnord-aurdalnord-frontrøgstadtrogstadgrimstadflakstadgjerstadxn--sandy-yuaxn--leagaviika-52bnore-og-uvdalvegarsheixn--rlingen-mxaxn--ggaviika-8ya47hvegårsheikarlsoykvitsoymasfjordenhamaroyinderoyosteroydavvenjárgasauheradguovdageaidnuxn--vre-eiker-k8abronnoysiellakkrødsheradkrodsheradkvinnheradbrønnøyxn--mtta-vrjjat-k7afxn--lrenskog-54akvitsøyvárggátkarlsøyosterøyinderøyhamarøybronnoysundxn--aurskog-hland-jnbbahccavuotnabáhccavuotnagiehtavuoatnastor-elvdalmidtre-gauldalxn--gildeskl-g0akarasjokevenassixn--bievt-0qaxn--yer-znalebesbynessebyxn--hbmer-xqamalselvmålselvxn--unjrga-rtamøre-og-romsdalmore-og-romsdalhareidmelandørlandorlandstrandålgårdsolundalgardafjordåfjorddielddanuorrikautokeinoxn--stre-toten-zcbskodjeaejriestangeliernebamblestokkefauskesnåasesnaasekongsvingerlangevagberlevagxn--flor-jrahattfjelldalostre-totenøstre-totenvestfoldxn--mely-iraálaheadjualaheadjunordreisaxn--troms-zuaxn--lgrd-poacporsangerflatangerstavangerleikangerbremangersamnangergieldakarasjohkaxn--rdy-0nabfrostautsirasnoasatromsaxn--sr-aurdal-l8aflekkefjordjølsterjolsteraremarkhedmarknååmesjevuemienaamesjevuemiexn--vard-jrarollagmeråkermerakerorskogørskogxn--bdddj-mrabdákŋoluoktaxn--osyro-wuaaknoluoktatrysilskjervøymandaljondalbindalrindalmeldalsuldalorkdalsigdalalvdallærdalhurdalsirdalverdallerdallardaloppdalåseralaseralhadselkragerødivttasvuotnaoverhallasteinkjerxn--hnefoss-q1askedsmokorsettromsøxn--dyry-iravestre-totenmuseumxn--sandnessjen-ogbrahkkeravjufylkesbiblbájddarbajddarxn--laheadju-7yarennesøyxn--koluokta-7ya57hxn--hgebostad-g3aleirfjordstorfjordbalsfjordbåtsfjordbatsfjordmuosátbievátloabátkárášjohkanøtterøyxn--mjndalen-64anordkappláhppilahppialstahaugsiljanverranrøykenroykenhaldenlyngenbergenhortenhønefosshonefosstroandinbeiarnvarggatosoyroosøyrotromsoidrettmuosatbievatruovatloabatvoagattynsetnessetxn--indery-fyaskánitskanitraholtråholtxn--ystre-slidre-ujbandebusarpsborgbearduxn--karlsy-fyahordalandjorpelandjørpelanddeatnuringsakersør-odalsor-odalxn--slt-elabringerikeaudnedalnittedalnissedalhemsedalslattumsurnadalxn--blt-elabelverumstjørdalnaustdalhjartdalgjøvikfyresdalhasviknarviklarvikgjovikmalvikgamviklenvikporsgrunnstjordalengerdaldrobakdrøbakxn--msy-ula0hvestvagoyxn--vgan-qoaxn--ryken-vuaxn--lten-graxn--stfold-9xaxn--hpmir-xqaxn--lury-iramálatvuopmimalatvuopmitysværkirkenesbirkenesmoskenesbáidárxn--fjord-lraxn--rdal-poabahcavuotnabáhcavuotnaxn--frde-gralindåsbearalvahkixn--hobl-iraráhkkerávjuxn--loabt-0qavågåáltábodøsundlundraderådeetnetimeholeauregrueoddavagavegaranatanaarnasolasulaaltalekafusavangbergkvamåmliamlibokntinnroangranosenoslobodorøstroststatåmotamotivguprivøyeroyerliermossvossxn--nvuotna-hwalusterlunnermarkerhábmerhabmerhvalerfjalerxn--rholt-mratysvarbaidarfitjargaularhápmirhapmirmelhusfosnesøksnesoksnestysneshemnesevenesflesbergeidsbergtonsbergtønsberglindasxn--sndre-land-0cbnamsosxn--srum-graøystre-slidreoystre-slidrevestre-slidretrondheimbalestrandxn--langevg-jxaaustrheimxn--skjk-soavagsoyaveroysandoykarmoyfinnoytranoyvestbytranbysykkylvenxn--hyanger-q1aspjelkavikandasuoloxn--fl-ziaxn--drbak-wuastathellexn--sr-varanger-ggbtelemarkxn--bhcavuotna-s4axn--porsgu-sta26fčáhcesuolocahcesuoloakrehamnåkrehamnsandøykarmøyfinnøytranøyvågsøyaverøynamdalseidxn--lesund-huabadaddjaxn--vegrshei-c0axn--btsfjord-9zagildeskålporsanguxn--trgstad-r1anávuotnanavuotnahammerfestxn--sgne-graxn--brnny-wuacibestadharstadnarviikaevenáššivestnesgjemnessandnesagdenesrennesoyxn--avery-yuaxn--tysvr-vrabearalváhkikongsbergspydebergrandabergxn--andy-iradavvesiidaxn--krdsherad-m8aporsáŋgufredrikstadbjerkreimringeburennebuaurskog-holandnotteroyxn--vgsy-qoa0jxn--rmskog-byaskierváivelandbyglandfrolandaurlandforsandxn--bjddar-ptamidsundålesundalesundfetsundfarsundovre-eikerøvre-eikerakershusxn--moreke-juasørfoldøstfoldostfoldsorfoldhøyangerhoyangerlevangerorkangertanangerxn--vestvgy-ixa6olillesandulsteinxn--rennesy-v1agranvinskjervoyxn--klbu-woalavagisxn--h-2faxn--ryrvik-byakafjordkåfjordseljordfolkebiblxn--gjvik-wuajevnakerxn--kfjord-iuabudejjuxn--kranghke-b0axn--davvenjrga-y4axn--rland-uuaxn--ldingen-q1axn--mlselv-iuaxn--rady-iraxn--linds-prabrumunddalxn--ygarden-p1amo-i-ranaeidskogrømskogromskoghjelmelandxn--finny-yuaxn--sr-odal-q1axn--skjervy-v1aballangenkvanangenkvænangengratangenxn--hmmrfeasta-s4acvossevangensuohkanxn--rde-ulaxn--mli-tlaxn--ksnes-uuanordlandskanlandskånlandsortlandfuoiskuxn--rros-graxn--hcesuolo-7ya35bxn--eveni-0qa01gagaivuotnagáivuotnaxn--seral-lradrammenmodalenmosjoenjan-mayentorskensteigengloppenxn--snes-poamatta-varjjatxn--sr-fron-q1aomasvuotnajessheimbådåddjåxn--krager-gyaxn--kvfjord-nxaxn--asky-iraxn--snase-nraxn--bidr-5nacholtålenxn--vads-jraxn--jlster-byamosjøenxn--rst-0nastavernxn--ostery-fyaxn--oppegrd-ixaxn--sknit-yqaxn--risa-5naoppegårdskiptvetrendalenholtalenxn--mot-tlaxn--lhppi-xqaxn--holtlen-hxaxn--srreisa-q1akopervikxn--muost-0qaxn--bmlo-grahokksundkvalsundegersundxn--karmy-yuaullensakerxn--hylandet-54axn--kvitsy-fyaxn--bod-2nalangevågberlevågkristiansandxn--rsta-frahornindalstjørdalshalsenstjordalshalsensandnessjoenhámmárfeastaxn--lrdal-srasør-fronsor-fronnord-odalkristiansundmátta-várjjatvestvågøynesoddennotoddenbuskerudøygardenoygardensalangenlavangenralingenrælingenlodingenlødingenleaŋgaviikalaakesvuemieleangaviikauenorgexn--srfold-byaaskvollxn--rskog-uuaxn--nry-yla5gxn--vry-yla5ghammarfeastaxn--rhkkervju-01afxn--givuotna-8yakommunekrokstadelvanedre-eikerhagebostadhægebostadxn--berlevg-jxakviteseidxn--s-1faxn--l-1faxn--nmesjevuemie-tcbafuosskomoårekemoarekexn--lt-liacxn--jrpeland-54asvalbardoppegardholmestrandtvedestrandsogndalsokndalarendalsunndalfolldalxn--krjohka-hwab49jlyngdaletnedalnorddalsaltdalgausdalskedsmovaksdalgjesdalstordalxn--frya-hraaarbortedrangedalxn--smna-graaurskog-hølandxn--vg-yiabtjeldsundhaugesundlindesnesxn--mre-og-romsdal-qqbxn--dnna-gradyntmpheremerseineshacknetenterprisecloudmineaccomaorimāoriorgmilcriiwigennetschoolhealthkiwigovtgeekxn--mori-qsacloudnsparliamentcomedorgcompronetedugovmuseumwebsitekinservicebarsywebsitebuildereerobookheimdnsleapcelleero-stagetechcrscsslorigingohomecdbedeeeiemesecabgngilnlalplchfisiincnnoroptatitmtltruauhulumkdkukskjplvtrgrfrkrhrusesismycynzcznetinteduassoososcloudstgbetaaezaeuhkusjshatenadiarycdn77hoptozaptois-a-knightmyftpno-ipjpnddnssdpdnsspdnsbarsysweetpepperis-a-bruinsfanis-very-sweetservegameis-a-soxfanhomelinuxcdn77-secureservebbsmisconfusedwebredirectblogsitefreedesktopcouchpotatofriestoolforgeaccesscamis-lostreadmyblogsmall-webfedorapeopleserveftpis-a-celticsfanmywirepotagertwmailin-dslsellsyourhomeread-booksfreeddnscable-modemis-savednflfanufcfanmlbfanstuff-4-saleendoftheinternetin-vpnmy-firewallhomeftpis-localis-a-chefboldlygoingnowherewebhopselfipkicks-assroxatunkcamdvrfedoraprojectgotdnsdvrdnsdyndnspubtlspimientahomeunixdontexistfedorainfracloudwmflabsfspagesbmoattachmentsteckidsfamilydsdnsaliasdynaliasnow-dnscloudnsdoomdnsduckdnsblogdnshomednsroutingthecloudendofinternetdsmynasip-dynamicpoivronhttpbinmyfirewallis-very-evilmysecuritycamerais-a-linux-userwmcloudis-a-geektuxfamilyis-a-candidatedoesntexistis-very-badhobby-sitegame-hostaltervistais-foundis-a-patsfandnsdojohepforgepodzonedynservcollegefanis-very-goodfrom-meis-very-niceisa-geeknerdpolacmedsldingorgcomnomgobabonetedupleskaemhlxmyboxrockyprvcydeuxfleurspdnscodebergheyflowstatichostorgmilcomnomgobneteduorgcomeduiorgmilcomngonetedugovcloudns1337ngrokacorggogfamcomwebgobnetedugokgopgkpgovgosbizpasaugumicsopozpapuwmwsrprusiskwpspkppspkmpspokeoiawsawifoumsdnskokwpmuppuppsppiwwiwoowuzswkzoschrzpisdnwzmiuwwitdpssewsseumigugimoirmpinbwinbwiihupporzgwgriwupowwskrwioswuozstarostwokonsulattmpccopruszkowmyspreadshopostrodakartuzyopolegminamediaustkazgorajgoraolawailawalomzawloclradombytomjaworznotargilubinkoninzagantorunkutnokepnonakloczestsopotsanokturekplockslasksklepzarowlukowmedaidgdaorgmilrelcomnomatmgsmartneteduelkgovwawsossexbiztgorysejnytychypomorzeboleslawiechomesklepsdscloudunicloudzakopanelegnicarawa-mazbydgoszczswidnikkrasnikwloclawekbielawamragowograjeworealestatebeskidykaszubymalopolskaprzeworskswiebodzinlecznadfirmaszkolawarmiagdyniamiastakazimierz-dolnymalborkswidnicadlugolekaostrolekapodlasieelblagtravelsimplesitezachpomormielecszczecinnieruchomosciwalbrzychlezajsklublinbedzinpoznanwielunmielnooleckostarachowicedkontopowiatwroclawrybniksuwalkileborkslupskgdanskostrowwlkptarnobrzegtourismwegrowkrakowglogowyou2pilanysamailwrocinfoagroautobeepshopprivlapypiszlodzcfolksecommerce-shopmazurypulawyskoczowrzeszowpomorskiezgierzkaliszolkuszlowiczostrowiecsosnowiecmazowszewodzislawbialowiezazgorzeleckatowicepabianicejelenia-gorawolominkarpaczsieradznowarudaczeladzkonskowolaskierniewiceswinoujscieturystykabieszczadycieszynketrzynolsztynbialystokbabia-goraprochowicewarszawastalowa-wolapolkowicegorlicegliwiceponiatowalimanowalubartowaugustowkobierzyceopocznognieznoszczytnokolobrzegshoparenapodhalebielskoklodzkostargardatwithplayitownnamecoorgnetedugovacorgcomproestnetedugovbiznameislaprofinforechtngrokmedaaaacacpaenglawjurbarbarsykeeneticavocatacctcloudnsorgcomsecplonetedugov123paginaweborgcomnetintedugovnomepublidkinbarsygovx443cloudnsorgmilcomnetedugovcooporgmilcomschnetedugovnamecomcannetlibassoaemclantmcontstoreorgcomnomrecwwwbarsyfirminfoshopartsstackitmyddnswebspacelima-cityacincooxorgedugovbarsybrendlyhbvpsvpsspectrumlandinghostingacppmordoviamcprecbgorgmilcomspbnetintedumsknovgovbirrasmcdirmytismircloudvladimirnalchikadygeyamarinepyatigorskmyjinobashkiriaeurodirvladikavkazna4ugroznykustanaikalmykiacldmaildagestaniranbuildcloudcanvaliaravalwixdevelopmentappwritemigrationneedleverceldatabasestackitcodereplravendbonporterlovableaccoorgmilnetgovcoopmedorgcompubschnetedugovservicemecomygovorggovtvmedorgcomnetedugovinfoedgfacbmlonihkutwpsryxzbdtmacfhppmyspreadshopbrandpartiorgcomfhvpress123minsidaitcouldbeworlanbibkommunalforbundfhskiopsyskomvuxkomforbnaturbruksgymnloginlineorgcomnetedugovenscaledeuusentsurgebotdaorgmilcomnetgovnowteleporthashbangplatformlovablebarsyshopwarebasehoplixbarsyonlinemsf5gitappgitpagewawamscofigma-govcaffeinefigmacanvasoltstscwputerbarsysupportchatgptsquareomniweopensocialcpanelplaycodenotionnovecorewpsquaredpreviewjelecyonbyensrhtfastvpspieboxconvexjouwwebheyflowplatformshloginlinemadethissourcecraftclouderaorgorgcomartedugouvunivmeorgcomnetedugovsurveysstatichfheiyuxs4allprojectmyfastubervibehostapp-ionosdeployagentmecoorgcomschnetedugovbizcncostoreorgmilcomneteduembaixadaconsuladokiraranohoprincipesaotomeheliohobarsystorebaseshopwaresellfyaiabkhaziavologdamordoviapenzalenugsochinavoiexnetspbmsknovnorth-kazakhstanashgabadkareliaarmeniageorgiavladimirnalchikivanovobukharaadygeyakhakassiakalugakrasnodarjambylaktyubinsktroitskbryanskobninskkurganazerbaijanpokrovskbashkiriatselinogradvladikavkazmurmansktulatuvamangyshlaktashkentchimkentgroznykaragandatermezarkhangelskkustanaikalmykiabalashoveast-kazakhstankaracoldagestantogliattibarsyredorgcomgobedumirenknightpointaccoorgjelasticdiscoursecleverappsschacmiincogoornetonlineshopcogoorgmilcomwebnicnetintedugovbiznametestcoorgmilcomnomnetedugovorangecloudpersoindorgcomfinnatnetgovensmincomtourismintlinfox0611oyaorgmilcomnetedugovquickconnectvpnplusnettprequalifymeaddrmyaddrntdllwadlnctvavdrk12orgmilpolbeltelcomwebgennetedutskkepgovbbsbiznameinfocoorgmilcompronetedugovbiznameinfobetter-thanworse-thansakurafromdyndnson-the-webmymailerorgmilurlcomneteduidvgovmydnsgameclubebizmeneacsccogotvorhotelmilmobiinfovodteiflgplkmsmsbcckhincndnvncoztltmkckppzpdprvcvkvlvcrkrkscxuzchernovtsyrivneyaltaodesavolynrovnolutskltdinforgcomnetedugovbizvinnicazhitomirternopilpoltavakropyvnytskyizaporizhzhiasevastopolsebastopoluzhgoroduzhhorodkharkovkharkivvinnytsiakhmelnytskyizaporizhzhecrimeaodessazhytomyrnikolaevcherkassydonetskluganskluhanskkirovogradivano-frankivskchernivtsikrymkievkyivlvivsumyzakarpattiamykolaivcherkasychernigovkhersonchernihivdnipropetrovskdnepropetrovskkhmelnitskiyneacsccogoorusorgmilcomedugovmyspreadshopadimono-ipbarsybarsyonlinelayershiftnh-servretrosnubapicampaignservicelugaffinitylotteryweeklylotteryraffleentrygluglugsmeaccoindependent-inquestnimsitecopropymntltdorgplcschnetgovnhsbarsyindependent-commissionindependent-reviewpolicepublic-inquiryindependent-panelconnhospindependent-inquiryroyal-commissionoraclegovcloudappscck12libaws-govccphxcclibpvtparochchtrcck12libcceatonk12coglibtecgendstmusann-arborwashtenawcck12glghcck12sealibforksolympiabainbridge-islkeyporthoquiamyarrow-pointcentraliaport-townsendsequimport-ludlowrentonsilverdalebremertonredmondsheltonbellevueport-orchardport-angeleskingstonchehalisaberdeengig-harborseattlepoulsboidmdndsddemenegacalamaiavawapailalflnmdcncscohnhmihiviwiriinmntnmocoutvtctmtgunjokakwvnvprarorasmskstxwynykyazisadninsnngosrvis-bymircloudservernamepointtoenscaledland-4-salefreeddnsstuff-4-saleazure-apinoipdatabricksappscloudnsgolffanheliohostazurewebsitesgvorgmilcomgubneteducoorgcomnetd0egvorgmilcomnetedugovmydnsiacostoree12orgmilcomnomwebgobbibrectecnetintedugovraremprendefirminfoartseducok12orgcomnethidnsidacaiiosonlahanamhanoicamauhueorgcompronetintedugovbizbacninhtayninhhoabinhnamdinhtravinhhaiphongvinhlonghaiduongquangnamquangtrithuathienhuequangninhbacgianghaugiangquangbinhsoctrangbentrethanhphohochiminhdanangkontumhatinhkhanhhoathanhhoahealthgialailaocaiyenbaibackanngheanlonganphuyenphuthocanthodaklakdongnainameinfovinhphucdongthapkiengiangtiengiangquangngailaichaulangsonlamdongdaknonghagiangangiangcaobangbinhduongninhthuanbinhthuanbaclieuthaibinhninhbinhbinhdinhtuyenquanghungyenbaria-vungtauthainguyendienbienbinhphuocschbizputerimagine-proxyorgcomnetedugovcloud66advisormypetsdyndnsxn--8dbq2axn--4dbgdty6cxn--5dbhl8dxn--hebda8bxn--80auxn--d1atxn--c1avgxn--o1acxn--o1achxn--90azhxn--55qx5dxn--uc0atvxn--od0algxn--wcvs22dxn--gmqw5axn--mxtq1mxn--12c1fe0brxn--h3cuzk1dixn--12co0c3b4evaxn--12cfi8ixb8lxn--o3cyx2axn--m3ch0j3axn--j1adpxn--90amcxn--90a1afxn--h1ahnxn--j1ael8bxn--h1alizxn--c1avgxn--j1aefxn--80aaa0cvacxn--41acaffeineexeopentunnelbotdashtelebitorgtmaccoagricorgmilnomwebnicngonetaltedugovlawnisschoolgrondaraccoorgmilcomschnetedugovbizinfoprg1-zeropstritonstackitlimazeropsaccoorgmilgovяспборгкоммскбизмирсамаракрымсочиакодпроргобрупрצהלממשלישובאקדמיהองค์กรธุรกิจรัฐบาลศึกษาทหารเน็ต教育網絡組織公司政府個人닷넷한국澳门新闻澳門联通家電嘉里招聘通販닷컴삼성コムგეбгрфеюadcdbdgdidmdsdtdaebedeeegeiejekemenepereseveyegabacalamanauavapaqasazacfbfafgfnfpfwftfbgcgagggegkgngmgsgpgvgtgugilmlnlalclglplsltlhmimjmkmmmomambmcmdmfmgmzmpmsmtmgbbblbsbecccacnclcmcvctcscmhkhghchbhthphshlinikifigiaibicivisikninhnmncnbngnsnpnvntnjoionomobocoaofodorosotoptstttytatbtetgtithtmtltrusuvuaucueuguhulumunufjdjbjtjsjlkmkhkfkdkcktkukskpkgpmpnpkpjpgqaqmqiqsvtvcvbvmvlvrwpwtwzwbwcwawgwkwmwtrsrprgrfrercrbrarnrmrlrkrirhrwsusrssspsgsesbsaslsmsissxmxaxcxuypysylymykygybycyuztzsznzmzkzdzczbzazελευ世界台灣购物公益点看臺灣网络書籍在线网站手机机构大拿游戏信息台湾谷歌慈善商标香港中国餐厅网址中國商城食品微博政务移动集团公司八卦商店健康网店政府时尚佛山中信娱乐广东企业homedepotengineeringاماراتrepublicankuokgroupversicherungchannelcitadelxn--pgbs0dhxn--b4w605ferdstatebankwebsitexn--mgb9awbf亚马逊淡马锡alibabaxn--ngbc5azdxn--mgbbh1axn--45br5cyltoshibabuildworldcloudtradeguideplacespacedancemoviephoneprimesmilebiblestyleappleazurestoreskypegripexn--l1accdrivelottehorsehouseleasechasereisestadahondaomegaaetnaamicaninjanokiamediadeltavodkaedekaosakapizzaslingemailgmailtirolshelltmallfinallegaltotalhotelamfamforumrehabmusicciticricohcoachwatchboschearthfaithirishmiamiarchidubaiguccipraxiみんなストアセールcanonsalononionnikonepsonkoelngreensevencrownikanoradioaudioweiboglobopromogalloyahoociscorodeovideomangobingotokyovolvolottokyotophotosmartsportquesttrusthyattjetztadultcymrubaidutushuxn--kprw13dubankclickblackmerckgroupsharpcheapnowtvxn--h2brj9cקוםհայоргсрбмонкомбелмкдқазрусукрمصرقطرعربكومdadcfdmedwedredphdthdbidpidkrdmsdltdiceonewmeglemoerwecfageacbanbambaaaammakianraspacpaaxawtfbcgaegongingaigvigorgdogdhlmilrilonlaolloluoljllcalgalnflafltelsrlfrllplkimibmcamcombommomifmabbjcbscbwebcabnabtabmlbpubabcbbcnecincpncllcstcwtcpwcnyckfhbzhovhmoiskiobisbitcifyituipinvinwinxincbnbcnmanfangdnmenrenkpnmtnyunrunfununobiojioriohbogmofooboooooacoecoceongoproartistottnttbbtcateatlatvetpetbetnethktmitfitintjothotgotdotbotprueduicujnjyouinknhktdkappsapgapmapdnptopgopllpjmpzipvipripesqtrvdtvitvdevmovgovhivnrwlawsewnewbmwwownowhowdvrftrmtrsfrbarcartvscrseusawsupsubssbsadsddsldssasbmsmlsxxxboxfoxgmxtjxsextaxbuyflydiysoyjoyskypaydaygayxyzanzbizwebersenerpokerlameractortatarsolarລາວคอมไทยtourslocusnexuslexusgiftsbeatsboatspartspressglassswissकॉमनेटtiresgivescodeshomesgamestunesshoescardswalesloansvegastoolsdealsautosparisファッションworkssucksrocksxeroxforexfedexpartylillymoneystudyrugbytoraytoday中文网xn--unup4y天主教飞利浦新加坡enterprises我爱你嘉里大酒店christmasxn--fct429kholdingsxn--8y0a063axn--mgbx4cd0ablifestyleabogadoallstatenetbankكاثوليكxn--s9brj9cxn--gk3at1ebestbuycharityxn--55qx5dmicrosoftpropertybasketballhomegoodscorsicajewelrygallerygrocerysurgerycountrybrusselsverisignferreroxn--czr694bhdfcbankcommbanksoftbankپاكستانپاکستانnextdirectالسعوديهالعليانxn--h2brj9c8cxn--80adxhksshikshaxn--mgbai9azgqp6jcuisinellabarclayscatholicxn--kpry57dcompanyxn--xhq521bblackfridayxn--mgba3a3ejtsandvikxn--d1acj3bacademydownloadمليسياxn--j1amhxn--w4r85el8fhu5dnraipirangaathletaxn--fhbeixn--mgbqly7cvafrzuerichxn--c2br7gஇலங்கைcontractorsxn--io0a7igraphicsinsurancetemasekxn--xkc2al3hye2amotorcyclesphotographydirectoryplumbingxn--vhquvclothingtrainingcleaningwilliamhilllightingxn--mgba3a4f16ashoppingcateringeducationokinawapicturesventuresproductionsxn--9et52uwalmartഭാരതംsupportrealestatecapitalonexn--nqv7fs00emaauspostfloristdentistxn--qxamgodaddybradescobargainsmitsubishikerryhotelsxn--9dbq2axn--3pxu8kimmobilienxn--fjq720axn--mgbtx2bholidaymckinseymadridbusinessbuildershelsinkixn--4gbrimмоскваالسعودیةcoffeedegreelacaixapartnersalsaceofficeabbvievoyageorangegeorgeonlinechromemobilekindlegoogleoraclecircleschulesecureinsurexn--mgba7c0bbn0aestatexn--mgbc0a9azcgcruisehangoutxn--vuq861bxn--42c2d9arexrothfirestoneuniversityxn--nnx388alifeinsuranceextraspaceонлайнvermögensberatersoftwarexn--fiqs8sxn--mgbab2bdxn--w4rs40ltiendaभारतम्africatoyotaotsukasakuracameracreditcardnagoyaconsultingnetworkjunipertheatermonsterprogressivepioneerxn--55qw42gracingdatingvotingvikinglivinggivingxn--bck1b9a5dre4cbrotherweatherjoburgفلسطينlplfinancialxn--clchc0ea0b2g2a9gcdfutbolschoolsocialglobaldentalwoodsidechanelairtelmatteltravelrealtorwebcamstreamభారత్unicomalstomxn--nodexn--6frz82gmuseumfurniturexn--rvc1e0am3exn--mix891faccenturexn--11b4c3dismailineustardiscountquebeccomsecclinicservicesxn--y9a3aqxn--c1avgswatchchurchsearchالاردنmarketingcontacthealthmonashshoujisanofitaipeiamericanexpresssuzukiアマゾンクラウドポイントbhartiグーグルxn--mgberp4a5d4armemorialxn--1qqw23alondonmormoninstitutevisionbostonnortoncouponmaisonamazonvirginberlindesigndurbanolayannissananquanxihuanhitachikaufengardenreisenbayerntechnologydatsunxn--90a3aclatinocasinostudiophysioxn--ngbe9e0apharmacytattootaobaoaramcoexpertreportabbottdirectselectimamatfairwindspictettargetmarketintuittravelersinsurancecreditdupontryukyusuppliesxn--tckwebnpparibasschmidtmerckmsdyodobashirestaurantbridgestonecricketxn--fpcrj9c3dbostikbroadwayattorneylefrakemerckxn--fiq228c5hscareersfarmerswinnersflowersxn--wgbh1cguitarsxn--54b7fta0ccxn--p1acfmakeupgalluplandroverxn--kcrx77d1x4agoldpointbauhausxn--mgbayh7gpahiphopplaystationxn--mgba3a4fraxn--eckvdtc9dhyundaixn--gckr3f0fistanbulticketsmarketsflightschintaireviewsxn--3e0b707ewindowsxn--fiqz9sfinancialxn--fzys8d69uvgmابوظبيdiscoverreviewবাংলাxn--5su34j936bgsgmoscowobserverapartmentsдетиارامكوсайтeurovisionxn--i1b6b1a6a2exn--xkc2dl3a5ee0hتونسموقعبارتڀارتشبكةعمانبيتكعراقreadkredbondlandbandfundfoodprodgoldfordtubecafesafelifeggeeieeefreefagepagegugezonewinememenamegamesaleablebikenikelikecarecbreherefiresaveloveliveblueartedatesitevotecaseluxebofamodaltdaasdatiaayogasinavanashiaasiajavabbvatevavivadatazaraarpacasavisasncfprofmaifsurfgolfdvagsongbingpingwangkpmggoogblogpohlfailcooldellcalldeallidlsarlfilmteamroomfarmimdbarabclubhdfcicbchsbcgmbhrichtechfishdishcashminiernikddiaudiwikimobitaxicitikiwidesiqponskinloanakdnwienopenporncerntownimmolimoolloinfonicofidolegosaxozeroaerovivoautovotomotofastbestresthostpostnextlgbtchatseatgiftmeetdietreitmintrentgentspotscotguruitausohumenucyoubanklinkpinkdclktalksilkbookseekworkrsvpaarpjeepshopcoophelpcamppccwshowbeerstarruhrflirweirhaircarsparsjprshausplusnewstipstoysjobskidsfanspicsdocsxboxamexsexynavycitysonyarmyallybabyplaydeliverybuzzgbizlamborghiniphilipsලංකාಭಾರತfitnessexpresslanxesspfizercenterwalterlawyersoccercareerkosherbrokerlockerdealerdoctorauthorxn--mgbqly7c0a67fbcvermögensberatungjaguarxn--pssy2uxn--hxt814eflickrrepairrogersairbusxn--mgbai9a5eva00beventsyachtsxn--t60b56aভাৰতভারতभारतभारोतviajeshermeshughesxn--j1aefसंगठनvillasଭାରତclaimshotelsભારતzapposphotosjuegoscondostatamotorsgratistennisਭਾਰਤtkmaxxtjmaxxschaeffleryandexxn--80aswgrealtysafetybeautyluxuryxn--3ds443gsupplyfamilyxn--o3cw4hhockeysydneyxn--90aenissayalipayenergycomputeragencyxn--rovu88b電訊盈科xn--gecrj9cstatefarmaccountantaquarelleolayangroup香格里拉xn--p1ai组织机构xn--1ck2e1bxn--mgbt3dhdschwarzموريتانياabudhabinowruzkomatsufujitsuhospitalxn--80asehdbxn--mgbtf8flxn--j6w193gxn--yfro4i67oprudentialxn--flw351ecruisescoursesrecipesxn--e1a4cferrarixn--ses554gxn--wgbl6awatchesstaplessinglesxn--mgbcpq6gpa1axn--otu796dpropertiescreditunionxn--mgbah1a3hjkrdstockholmhisamitsuالسعوديةstcgroupdomainsoriginscouponsbloombergclubmedfroganslimitedxn--80aqecdr1aexposedinternationalequipmentbarclaycardxn--q7ce6axn--mgbi4ecexpprotectionassociatesconstructionxn--cck2b3bxn--45q11candroidfoundationישראלxn--mgbca7dzdocliniqueboutiqueengineerxn--qxa6asystemsfirmdalefashionauctionxn--nqv7finfinitirentalsreliancetradingweddingfishinghostinggentingbookingcookingxn--3hcrj9cgraingerxn--czrs0tdemocratsamsungyokohamaxn--h2breg3evexn--nyqy26alundbeckmelbournevacationssolutionsfrontierxn--vermgensberatung-pwbmanagementxn--cg4bkixn--mgb2ddeslincolnhamburgsandvikcoromantblockbusterairforcebarefootxn--4dbrk0ceinvestmentsfeedbackcommunityxn--ngbrxالبحرينdiamondsamsterdamhealthcareredumbrellaxn--mxtq1mxn--2scrj9cagakhanxn--mgbpl2fhкатоликcaravanசிங்கப்பூர்richardlimortgageamericanfamilyxn--fzc2c9e2cscholarshipssaarlandxn--imr513nvlaanderensamsclubgoodyearkitchenஇந்தியாweatherchannelallfinanzxn--kput3iالسعودیۃxn--90aisxn--efvy88hالجزائرxn--mgbaam7a8hexchangejpmorganxn--tiq49xqyjfidelitysecurityxn--mk1bu44cwanggouxn--fiq64bxn--6qq986b3xlxn--mgbbh1a71exn--80ao21amarshallsxn--5tzm5gtravelerspanasoniclatrobeyoutubeaccountantsxn--rhqv96gxn--cckwcxetdanalyticsxn--ygbi2ammxبازاربھارتسوريةorganicfreseniusسورياxn--9krt00axn--qcka1pmcxn--jlq480n2rgdeloittesciencefinancexn--jvr189mxn--30rr7yhomesensehotmailbaseballfootballleclercboehringerxn--q9jyb4cxn--mix082fاليمنهمراهpolitieسودانايرانایرانnetflixyamaxunxn--lgbbat1ad8jcollegestoragecapetowncolognekerrypropertiesxn--mgbgu82axn--ogbpf8flxn--czru2dwhoswhociprianilasallexn--g2xx48cforsalebanamexaudiblexn--vermgensberater-ctbxn--zfr164bericssonvanguardxn--45brj9cindustriestheatremarriottxn--3bst00mcomparexn--mgberp4a5d4a87gcapitaldigitalالمغربbarcelonashangrilaxn--d1alfcalvinkleinwwwcitysapporokawasakinagoyasendaikobekitakyushuyokohamackjp";
	//#endregion
	//#region node_modules/.pnpm/tldts@7.4.15/node_modules/tldts/dist/es6/src/suffix-trie.js
	const numberOfNodes = nodeFlags.length;
	const numberOfEdges = edgeLength.length;
	const edgeOffset = new Uint32Array(numberOfEdges);
	const edgeHash = new Uint32Array(numberOfEdges);
	const wildcardEdge = new Int32Array(numberOfNodes).fill(-1);
	for (let node = 0, offset = 0; node < numberOfNodes; node += 1) for (let edge = edgeStart[node]; edge < edgeStart[node + 1]; edge += 1) {
		edgeOffset[edge] = offset;
		const end = offset + edgeLength[edge];
		let hash = 5381;
		for (let i = end - 1; i >= offset; i -= 1) hash = hash * 33 ^ labelText.charCodeAt(i);
		edgeHash[edge] = hash >>> 0;
		if (edgeLength[edge] === 1 && "orgmilcomschnetedugovdrrformsfeedbackofficialaccoorgmilschnetgovmagazinemediaunioncargopilotgroupcaarespressworksaerodromeworkinggroupair-traffic-controlaircraftaccident-preventioneducatormarketplaceambulanceinsurancecateringairportrepbodyenginesoftwaremodellingair-surveillanceconsultingchartertrainermaintenanceservicesdesignflightskydivingfreightassociationstudentgroundhandlingdgcafuelclubtaxicrewshowballooningexpresstraderbrokerauthoragentsairtrafficjournalistsafetyconsultantmicrolightaccident-investigationparachutingequipmentproductionfederationrecreationscientistnavigationengineertradingglidingleasingresearchpassenger-associationentertainmentparaglidinghangglidingaerobaticrotorcraftemergencycertificationgovernmentaeroclubexchangelogisticschampionshiphomebuiltcouncilconferencecontrolairlinecivilaviationjournalorgcomnetedugovcoorgcomnomnetobjofforgcomnetuwukiloappsframerorgmilcomnetedugovcoradioorgcomnetcommuneedogpbcoitgvorgedugov*spreviewfrontendrelayononstagingupid*mtls*privatelinktypedreamdeveloperbravemochawindsurfaivenmirenupsunwnextbegetngrokclerkwale2bwebcsbrunputerflutterflowspawnbaseshiptodaymagicpatternsnetlifyondigitaloceanrailwayhostedclaudehasurabotdashvercelgithubluyanigadgetreplitcloudflaretelebitedgecomputeevervaultexponyatnoopencrpplxzeaburwasmerframerzeropsrocketpreviewconvexmedusajsspritesonherculeseasypanelstreamlitsnowflakemesserliloginlinehackclubcodepennorthflankbase44corespeedleapcellngrok-freeclerkstagelovableon-fleek*us-west-3ap-south-2us-central-2us-central-1eu-central-1ap-south-1us-west-2us-east-2eu-north-1ap-north-1us-west-1us-east-1*rcloudintsegorgmilcomgobbetnetintedugovturmusicasenasamutualcoopip6uriurnin-addre164homeirisgovdixdaemoncloudnssthwien*inexexkunden4accogvormymyspreadshop4lima2ixortsinfofuturecmsfuturehosting12hpprivfuturemailinglima-cityfunkfeuer123webseitednshomemelmyspreadshopcloudletswasantqldvicactnswtascatholicwasaqldvictasidwasantozqldorgcomvicasnactnetedugovnswtasconfcomairflowlambda-urltransfer-webappairflowtransfer-webapptransfer-webapptransfer-webapp-fipstransfer-webappeu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1privatenotebookstudiolabelingnotebookstudionotebooknotebook-fipslabelingnotebookstudionotebook-fipsnotebookstudio-fipsnotebook-fipsnotebookstudionotebook-fipsnotebookstudioeu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2experimentsus-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1onrepostsagemakercopporgmilcompronetintedugovbiznameinfoshoprsorgmilcomnetedugovbrendlyresolvenzauscotvstoreorgcomnetedugovbizinfoidacaicoittvorgmilcomschnetedugovinfocloudezproxyacmymyspreadshopkuleuvenwebhostingtransurl123websitecloudnsinterhostsolutionsddns5476103298edgfacbmlonihkjutwvqpsryxzbarsycoororgcomedumyftpno-iporxcloud-ipfor-somemmafanfor-morewebhopselfipjozidyndnscloudnsdscloudfor-thefor-betteractivetrailcoeconorestooteorgcomeconeteduassurmoneyafricaarchitectesrestaurantloisirstourismavocatsinfoagrounivcoorgcomnetedugoviatvdeportesaludtksatorgmilcomwebgobnetinteducienciaboliviarevistacooperativaempresanombreindustriamusicapatriamedicinademocraciapoliticapuebloindigenaplurinacionalarteblogwikiinfoagrotransportenoticiasprofesionalacademiaeconomiaecologiamovimientotecnologianaturalsimplesitecepesebamapadfmgalampbacscpirngorotomtrjspaprrprrsesmscepesebamapadfmgalampbacscpirngorotomtrjspaprrprrsesms*biaamfmtcmptvfeirasampajampanatalbelemananiradiog12medindfndbmdtrdthepoaggfjdfdefinfenflegsegongengcngorgzlgslglogppgmillelqslcimcomnomadmjabimbbibbsbabcrectecsjcetcpscpvhudieticriapipsiecnbiorioecogeoteoodoproatoartfstmatvetdetbetnetcntnotfotgrueduajuespappreptmpemparqsrvadvdevgovntrturagrjorfarjusmusdesvixxyzcozfozslzbhzmaringasantamariacampinagrandegoianiasorocabafloripasaobernardocuritibaboavistarecifeaparecidasaogoncasalvadorcuiabamorenamacapalondrinacontagemsocialfortalmaceioleilaoosascoriobranconiteroi9guacutcheblogflogvlogwikitaxicoopmanauspalmascaxiasjoinvillebaruericampinassantoandreribeiraoriopretoweorgcomnetedugovv0windsurfshiptodaycloudsitecoaccoorgnetgovofmilcomgovmediatechzacoorgcomnetedugsjgovmydnspenfnlabnbmbgcbcqconcontnuyksknsmyspreadshopno-ipawdevboxbarsyonidatemfuinabusavinstanceseceuguukussryzespawncsxcloud-ipmyphotosfantasyleaguetwmailcleverappsscrappingccwucloudnsftpaccessgame-serverccgovobjectsrmalpgcust*svcalp1aeappenginermalpgmyspreadshop4lima2ixsquare7cloudscale123websitefirenet12hpflowgotdnslinkyard-cloudcloudnslima-citydnskingobjectstorageedaccogoorusorgcomnetinteduaéroportxn--aroport-byaassogouvcomilgobgovcloudnses-1eu-west-1us-east-1euvipit1eurarubait1s3lbwebsites3websiteru-spbru-mskelasticcsrunstnukukcaukusnl-ams-1fr-par-1fr-par-2functionsnodess3ddlwhmrdbfnck8sifrs3-websitecockpitscblmgdbdtwhkafkpubprivs3ddlwhmrdbk8sifrs3-websitecockpitscblmgdbdtwhkafks3ddlrdbk8sifrs3-websitecockpitscblmgdbdtwhkafkk8sscalebookpl-wawfr-parnl-amsbaremetalsmartlabelinginstancesdechk2kuleuvenlaravelvoorloperurownoxazapscwhstgrvaporonline-serverobservablehqelementorantagonistreclaimjoteluluencowaydiademjelasticmatlabmagentositetrendhostingaxarnetperspectajenv-arubajelejoteravendbemergenttrafficplexconvexkeliwebserveboltbegetcdnstaticson-rancherprimetelonstackitunison-servicesdnshomelinkyardbarsyjelecloudnscocomnetgovmycn-northwest-1cn-north-1s3s3-accesspoints3-websites3s3-accesspointrdsdualstacks3-deprecatedemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspoints3s3-accesspointrdsdualstackemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicn-northwest-1cn-north-1cn-northwest-1ebcomputeelbcn-north-1airflowcn-northwest-1cn-north-1oncn-northwest-1cn-north-1amazonawssagemakeramazonwebservicesdirectasgdsdhehahljlnmhbacscahqhshhihnlnynsnmofjbjzjxjtjhkcqtwgsjssxnxjxgxxzgz網絡网络公司orgmilcomnetedugovxn--55qx5dcanva-appsxn--io0a7iquickconnectcanvasitekhsjxn--od0algcanva-codemyqnapcloudsrvrlessclustersrealtimestorageleadpagescarrdcrdorgmilcomnomnetedugovhidnssupabaserdpareplmypiumsoxmitotaplpagesfirewalledreplitowodevwebview-assetsvfswebview-assetss3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9eu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1s3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackanalytics-gatewayemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspointdualstacks3-deprecateds3-websites3-object-lambdaexecute-apis3s3-accesspoints3-websites3-accesspoint-fipss3-fipss3s3-accesspointdualstackemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackemrappui-prods3-websites3-accesspoint-fipss3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9vfss3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9eu-west-3ap-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1us-northeast-1ap-southeast-1me-south-1af-south-1ap-south-1ap-southeast-7us-west-2eu-west-2ap-east-2us-east-2ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ap-southeast-6ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1mrapaccesspoints3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3eu-west-3ap-south-2eu-south-2computes3-ap-northeast-2elbrdss3-ap-east-1s3-sa-east-1s3-us-gov-west-1s3-eu-central-1s3-ca-central-1eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3s3-website-us-west-2s3-website-eu-west-1s3-external-1eu-central-1me-central-1ca-central-1il-central-1s3-us-west-1s3-eu-west-1s3-website-sa-east-1s3-website-ap-southeast-2ap-northeast-1ap-southeast-1s3-us-west-2s3-eu-west-2me-south-1af-south-1eu-south-1ap-south-1us-west-2eu-west-2us-east-2s3-website-ap-southeast-1s3-1s3-globals3-ap-northeast-3eu-north-1airflowap-southeast-2s3-us-gov-east-1s3-fips-us-gov-east-1s3-me-south-1s3-ap-south-1ap-northeast-2s3-website-us-west-1ap-southeast-5s3-eu-north-1s3-ap-southeast-1s3-website-us-gov-west-1compute-1s3-eu-west-3us-gov-west-1s3-website-ap-northeast-1us-gov-east-1s3-fips-us-gov-west-1s3-website-us-east-1s3-ap-southeast-2ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1s3-us-east-2s3-ap-northeast-1authauthauth-fipsauth-fipseu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1rframeservicesbuilderstg-builderdev-builder*ociocpocsazuregcpawsdemoinstanceeu-west-3eu-south-2ap-southeast-3ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1previeweu-4us-4us-1eu-1us-2eu-2us-3eu-3appscomputepaasrag-cloudrag-cloud-chjcloudjcloud-ver-jpcdemonodebalancermembersipeuxvsoncillaocelotonzayalilynxsphinxfentigercustomercaracalo365cloudstaticxendevapp001testcode-builder-stgplatformmediasiteprojedrydpagesjsx0desazacncoitrueu4uhkukgrbrushatenadiarymyspreadshopfrom-flfrom-wvwebspace-hosttheworkpchatenablogcursorusercontentservesarcasmapplinzisakuratanwixsiteappchizigiizeis-into-carsdnsiskinkyadobeaemcloudis-a-therapistpgfogmyvncdojinis-an-actress1kappfldrvkozowqa2jpnmexprgmrfirewall-gatewaydynnscafjsfbsbxooguyfrom-gawoltlab-demois-a-anarchistwiardwebteaches-yogadattowebtb-hostinglive-websiteservegamegotpantheonfrom-nhsubsc-payfrom-ohvipsinaappfrom-cadyndns-officehomelinuxfrom-mahercules-appservebbsstreakusercontentfrom-okfrom-wyfastly-terrariumis-a-llamaqualyhqportalserveexchangeon-vaporvivenushopciscofreakgrayjayleaguesmetaaiusercontentfrom-iais-a-libertariansaves-the-whalestaveusercontentyolasiteoperaunitepoint2thisis-a-catererclaudeusercontentlinodeusercontentfrom-vagithubusercontentsells-for-lesshosteurcanva-appsplaystation-cloudddnsfreefrom-pafrom-prfrom-waddnskingoutsystemscloudhotelwithflightmydattois-a-nascarfanmydbserverminiserverdamnserverservehumouris-a-playerfrom-nvfrom-nmemergentagentgentappsamplifyappfrom-kyis-an-accountantnfshostserveircfrom-akpythonanywherestackhero-networkpostman-echolikescandydyndns-mailobservableusercontentserveftpfreeboxosfrom-utcdn77-storageamazonawsneat-urldyndns-serverlinodeis-a-teacherfrom-vtgleezemythic-beastsus1-pleniteu1-plenitla1-plenitpaywhirlservecounterstrikejdevcloudhealth-carereformis-into-animegoogleapisis-a-painterafricaisa-hockeynutatmetais-an-actora2hostedis-a-democratdatadetectest-le-patrondigitaloceanspacesis-a-designeris-a-hunterlinodeobjectstemp-dnsissmarterthanyoufrom-arsimplesiteevennodetownnews-stagingis-a-liberalgooglecodejelasticservemp3qualyhqpartnerdyndns-free1cooldnsest-a-la-masiondrayddnsdynuddnsfrom-orfrom-miis-a-bloggerfrom-himydobisscanvacodeis-an-engineerest-a-la-maisonupsunappdevinappswafflecellmyasustorwpenginepoweredfrom-ctservep2psame-appmyshopblocksthingdustdatalikes-piediscordsezis-with-thebandlpusercontentis-leetshopitsite3utilitiesis-a-personaltrainersinaappladeskis-a-cheflogoipselfipbase44-sandboxnospamproxyalibabacloudcsmesswithdnsauthgearappsiamallamawithgooglelutrausercontentmochausercontentframercanvasmytabitdyndns-homew-credentialless-staticblitzcpserverdiscordsaysis-a-nurseappspotatlassian-isolated-3premotewdfrom-mtwixstudiocode0emm180rmyactivedirectoryawsappsmytuleapdnsabrpolyspaceqbuserrenderbuiltwithdarkboutirgotdnsabrdnsdopaascanva-hosted-embedawsglobalacceleratorhomesecuritypcmyiphostditchyouripclever-clouddyndns-ipon-aptibleis-a-musicianhosted-by-filessecuritytacticsappspaceusercontenthomeunixstrapiappsame-previewcf-ipfsmycloudnaselasticbeanstalkis-certifieddontexistkasserverik-serverdrive-platformatlassian-3pfirebaseappherokuappawsapprunnerbarsycenteris-a-cubicle-slaveservehttpmyshopifyis-a-guruquicksytessiiitesorsitesmagicpatternsappis-a-cpameteorappfrom-wiis-a-rockstarbumbleshrimpdattolocaldatabricksappsreadthedocs-hostedfrom-rifamilydsdyndns-picsplesknsbplaceddnsaliasdynaliasdyndns-remotedoomdnsip-ddnsblogdnsis-a-doctorroutingthecloudamazoncognitobarsyonlinedsmynasddnsgurucloudflare-ipfsdeus-canvasfrom-idsmushcdnpagespeedmobilizerdyndns-at-homeunusualpersonhosted-by-previderis-a-republicandyn-o-saurstreamlitappworkisboringonthewificprapidqualifioappis-uberleetis-slickgetmyipwpdevcloudtypeformdyndns-at-workgentlentapismynascloudw-corp-staticblitzfrom-ingeekgalaxyservebeerfrom-mdonrenderspace-to-rentaivencloudappspacehostedwafaicloudcodespotblogspotatlassian-3p-us-gov-modfrom-ndfrom-msis-a-techieis-a-studentcustomer-ociis-a-photographerdurumisfrom-ksmassivegriddyndns-wikiis-an-entertaineris-a-hard-workermysecuritycamerafrom-mnrackmazedyndns-blogis-a-bulls-fanwritesthisblogfreemyipsimple-urlfrom-sdreservdauthgear-stagingest-mon-blogueuris-into-gamesrice-labsxtooldevicesakurawebis-an-anarchistoraclecloudappsdyndns-worksells-for-urhcloudfrom-dcfastvps-serverwpmucdnis-a-geekscrysecfrom-txis-into-cartoonsmodelscapetrycloudflarelocaltonetstreak-linkbalena-devicesfrom-njforgeblocksfreebox-oswebadorsitefrom-ncdoesntexisthobby-sitestreaklinkshomesecuritymacownprovidertuleap-partnersdattorelaywphostedmailservequakeis-a-socialistservehalflifepivohostingdynuhostingquipelementsw-staticblitzdyndns-webfrom-deproject-studyaliases121is-not-certifiedhercules-devis-a-financialadvisorservepicsis-a-greenloseyouripfrom-ilwithyoutubemwcloudnonprodwiredbladehostingdnsdojofrom-tnpixolinomyqnapcloudis-an-artisthostedpiis-a-landscaperauiusercontentoaiusercontenton-forgeis-a-conservativedreamhostersnet-freaksapps-1and1is-goneencoreapifastly-edgefrom-nesalesforcefrom-scdeployagentoraclegovcloudappsfrom-alis-a-lawyercechirevultrobjectsstufftoreadisa-geekddnsgeeklovableprojecttry-snowplowfrom-moblogsyteis-a-bookkeepernogmyforumravendbmyboxdeelementoredsaacficogoorinforgcomgobnatneteduidstoreorgcomnetintedudevnomepublorgcomneteduathgovtestscalculatorspaynowinfoquizzesresearchedcloudnsfunnelsassessmentsjscaleforcetmacltdorgmilcompronetgovbizpresseklogesrsccloudcustomfltusrcloude4corealmgovmunicontentproxy9metacentrumdyndyndyndnsdynpagespages-researchitionoccustomercomymyspreadshopipv64diskussionsbereich4limacomrub2ixfirewall-gatewayddnssspdnsbarsykeymachinesquare7myhome-serverspeedpartnercommunity-proschuldockxenonconnectgünstigliefernbwcloud-os-instancedyndnssecmy-routerxn--gnstigliefern-wobin-butterl-o-g-i-nisteingeekin-dslin-berlinin-brbfuettertdasnetzleitungsenin-vpnlcube-serverdyn-ip24logoipdyn-berlinruhr-uni-bochum12hpgoipsrvdnsfruskygit-repossvn-reposinternet-dnsgünstigbestellenhome-webserverxn--gnstigbestellen-zvbbplacedheimdnscosidnswebspaceconfiglima-citydyndns1istmeinvirtualuserschulplattformmy-gatewayddnsseclebtimnetztest-iservmein-iservvirtual-userhome64iservschuletaifun-dnstraeumtgeradeschulserverdynamisches-dns123webseitednshomehs-heilbronndnsupdaterbssgraphicdwadpdwdaepeweaawapaafpfwfabwbpbacwcpcciwebuserapiobjectsidsiskospockkimodorikerbonesteamsparisjanewaypicardglobaltarpitreedpikekiraworfsulukirkarchertuckerhackercanarywesleystagingprereleaset3r2lpbravepanelngrokiservstglclcrmerpflypagesbarsyvivenushoplocalcertlocalplayerbearbloggatewaydeno-stagingis-not-ais-a-goodbotdashvercelmocha-sandboxplatter-appreplitgithubpreviewworkersinbrowserevervaultis-ahrsndenoxmitmodxmyaddrstorageapipayloadgrebedocruncontainersstgstagelclstageloginlineis-a-fullstackcodepenleapcellngrok-freeis-coolstoragewebharemediatechlibp2pdiscourseimaginecomyspreadshopstoreregbiz123hjemmesidefirmcoorgcomnetedugovsldorgmilcomwebgobartnetedugovtmorgpolcomsocartnetedugovassoagrondiscoodontk12medcuegyecpaabgengorgmilgalsaltulcomadmesmgobpubdocmonfindgnriouioproartlatvetnetfotedulojgovntrturibrbarxxxofficialbasechefprofmktgpsictechinfoarqtcontdentrrpppsiqgit-pagesritmedfieorgcomlibprieduaipgovriikmeactvsportorgmilcomscieunnetedugovnameinfopintouchtawktotawkmyspreadshoporgcomnomgobedu123miwebcomputeorgcomnetedugovbiznameinfocognito-idpeusc-de-east-1onjelasticnxaspdnsbarsydirectwpdeuxfleurstransurldogadoprvwcloudnsamazonwebservicesdnshomeuserpartycokoobinmkmfidymyspreadshopalandkapsiikixn--hkkinen-5wacloudplatformhäkkinen123kotisivuidacorgmilcompronetedugovbiznameinforadioorgcomneteduuserexperts-comptablestmmyspreadshopgretaprdcomnomynhccifbxoshuissier-justicenotairesaeroportfreeboxoson-webavocatassoportgouvkdnschirurgiens-dentistes-en-franceavouesfbx-os123sitewebveterinairechirurgiens-dentistespharmacienchambagrimedecinfreebox-osdediboxgoupilemszicpyicpvicppleysheezypagesedugovcnpyorgcomcybllcpvtnetedugovtnxonlineschooldaemond6atcopanelorgnetplybotdashstackitkaasorgmilcomnetedugovbizmodltdorgcomedugovcoorgcomneteduappwriteacorgcomnetedugovcloudtranslateusercontentorgcomnetedumobiassoorgcomnetedugovbarsysimplesitediscourseindorgmilcomgobneteduorgcomwebnetedugovguaminfonxhra教育敎育網絡网絡组織組織网络網络组织組织公司政府個人个人箇人ltdorgcomincneteduidvgovxn--uc0ay4axn--55qx5dxn--mk0axixn--io0a7ixn--uc0atvxn--zf0avxxn--lcvr32dxn--od0algxn--wcvs22dxn--gmqw5axn--od0aq3bxn--mxtq1mxn--ciqpnxn--tn0agxn--gmq050iorgmilcomgobneteduiservwp2tempurlmircloudfreesitewpmudevmyfastgadgetcloudaccessjelehalfboltfastvpsemergenteasypanelopencraftizcombrendlynamefromrtpersoadultmedorgpolrelcomproartnetedufirminfoassoshopcoopgouvtmcomediahotelforumvideosportorgsexagrargameslakaseroticaerotikatozsdereklamcasino2000filmsuliinfoboltshopprivnewsszexcityutazasjogaszkonyveloingatlaneacaicogoormyᬩᬮᬶmilwebschnetkopbizzonedesaponpesxn--9tfkymyspreadshopgovmytabittabitorderravpageaccok12idforgnetgovmuniltdplcaccotttvorgcomnetmeca6g5gpgamubacaicniocoukuptverdruscsdelhiindorgmilcomwebnicfingenpronetintedugovresbizbiharbarsyinternetbusinessschooltravelsupabasealumnigujaratfirminfoaeropostbankcoopindevscloudnsno-ipbarsybarrell-of-knowledgebarrel-of-knowledgensupdategroks-thisdnsupdatefor-ourknowsitalldvrcammittwalddynamic-dnsv-infowebhopselfipdyndnshere-for-moreilovecollegemayfirstforumzcloudnsmittwaldservertypo3servergroks-theeusekd1cdndyndnsidrawsainaueuapjpusstagemocksysdevicesclientcustreservdcustdevdisrecprodtestingcobeebyteutwenteboxfusebravepstmndedynngrokorgmilcomnomnetedugovqcxqzzbarsythingdustmo-siemensrb-hostingfh-muenstergitbookbluebitecloudbeesusercontentnodeartkiloappsforgerockdarklangresinstagingapigeebubbleb-datascryptedhypernodedappnodepantheonsitegitlabgithubkeeneticvirtualservercleverappshostyhostingon-rioedugitticketstelebitwixstudioon-k3sicp0icp12038jeleqotolairbubbleappsmyaddrstolosmyrdbxwebflowdrive-platformbeagleboardhasura-applolipopdefinimavaporcloudmusicianwebflowtestazurecontainerresindevicereadthedocsloginlineeditorxmoonscalesandcatsbasicserverwebthingsbrowsersafetymarkbeebyteappbitbucketidaccovistablogorgschnetgovxn--mgba3a4f16axn--mgba3a4fraarvanedgeايرانایرانjclaspeziapdudcefegelemeperetevebacanatavaparasabgagfgogrgpgalclblimfmrmcbmbvbfclcmcvcrcpcchlimifibicivipirisimncnbnanenrnpntnnolomobocoaogorosopotoptvtatctbtmtltotpusulunutpspapaqsvpvvvtvavvrtrsrprgrfrcrbrarorkrvstsssbscsmsispzczbzbozen-suedtirolmyspreadshopxn--bulsan-sdtirol-nsbxn--valledaoste-ebbtrentinoaltoadigetrentin-sued-tirolxn--forlcesena-c8axn--forl-cesena-fcbxn--bozen-sdtirol-2obtriestetrentinsuedtiroltrentino-s-tirollecceudineaostesienaparmaluccapaviagenoapaduaaostamonzaabruzzoternirietiturinmilanbozenlaziofermoleccocuneonuoropratola-speziavdataaligfvgpugmolcalcamlomumbsicpmnvenvaoedugovabrsarmaremrbastoslazibxosfirenzetrentinosüdtirolval-d-aostavalle-aostamessinacremonaravennatoscanatrentin-suedtirolbolognacalabriaurbinopesarofriuli-v-giuliaogliastraxn--valle-aoste-ebblaquilaandriatranibarlettasyncloudxn--valle-d-aoste-ehbaostavalleyvalled-aostatrentino-alto-adigevallee-d-aostexn--balsan-sdtirol-nsbpistoiasicilialucaniacataniaiserniaperugiabresciaveneziagorizialiguriaimperiabulsan-suedtirolbalsan-suedtirolbarlettatraniandriaxn--trentino-sdtirol-szbforlì-cesenatuscanyvallée-d-aostemantovavallée-aostecasertapiemontevalleaostaval-daostafriulivgiuliatrevisoforli-cesenavalléedaosteferrarapescaravald-aostatrentino-altoadigefriuli-vegiuliavallee-aostecarboniaiglesiastarantomediocampidanovalleedaostetrentinosud-tirolcampobassotrentinsüd-tiroltrentinosüd-tirolmonzabrianzatrentino-südtirolxn--trentino-sd-tirol-c3bpotenzacosenzavicenzaemiliaromagnavenicefrosinonemarchepordenonetrentinosued-tirolvaresemolisevalléeaostefriuli-veneziagiuliabasilicatalatinaanconasavonaveronamodenabiellabolzano-altoadigepugliafoggiaumbriatrentino-stirolgenovapadovamateranovararagusapiacenzatrentinostirolvalleeaostetempio-olbiasudsardegnatrentinsudtirolmassa-carrarafriuliveneziagiuliatrentinosuedtirolandria-barletta-tranitrapanixn--cesenaforl-i8amaceratacaltanissettaascoli-picenobrindisicarraramassacagliaririmininapolivibo-valentiachietibulsan-sudtirolbalsan-sudtiroltrentino-a-adigebulsanbalsaniglesiascarboniamilanotorinoteramodell-ogliastraarezzotrentinoalto-adigerovigotrentovenetoiglesias-carboniatrentino-sud-tirolaltoadigereggio-emiliareggio-calabriasardegnatranibarlettaandriapiedmontxn--sdtirol-n2amedio-campidanotrentino-süd-tirolfriuli-vgiuliafriuli-ve-giuliaromeennaromapisa32-b16-b64-blodiastibarineencomonaplesforlicesenailiadboxosalessandriasicilytrani-barletta-andriaxn--trentin-sdtirol-7vbpesarourbinotrentinsued-tirolcesena-forliforlìcesenaemilia-romagnamonzaebrianzaxn--trentinsdtirol-nsbtrentinos-tiroltrentinsüdtirolvalledaostaolbia-tempiocampidanomediovibovalentiasassarivalle-daostalombardysud-sardegnafriulivegiuliareggioemiliamonzaedellabrianzaalto-adigevercellitrentin-sudtiroltraniandriabarlettatrentino-sudtirolascolipicenobozen-südtirolfriulive-giuliaflorencexn--cesena-forl-mcbcarbonia-iglesiasaosta-valleycarrara-massadellogliastratrentinoa-adigexn--valleaoste-e7apesaro-urbinoxn--trentinosdtirol-7vbxn--trentin-sd-tirol-rzbxn--trentinsd-tirol-6vbtrani-andria-barlettatrentin-süd-tirolxn--trentinosd-tirol-rzbgrossetomonza-e-della-brianzasüdtirolreggiocalabriatrentinoaadigetrentin-südtirolverbano-cusio-ossolafriuliv-giuliaverbaniacampaniatrentino-aadigefriulivenezia-giuliasardiniaandriabarlettatranibarletta-trani-andriacatanzarooristanourbino-pesarocesena-forlìvalle-d-aostacampidano-medio123homepagesiracusatempioolbiasuedtirollombardiaavellinocesenaforlìtrentinofriuli-venezia-giuliabozen-sudtirolandria-trani-barlettabulsan-südtirolbalsan-südtirolmonza-brianzabolzanotrentino-sued-tirolbellunosalernolivornocrotonesondriodnshometrentinsud-tirolmassacarraratrentin-sud-tiroltrentino-suedtirolviterbobergamocesenaforliolbiatempiopalermobeneventoagrigentoofcoorgnetfmaitvphdengorgmilcomschnetedugovperagrikanieasukehandachitatokaiaisaikonanoharuamaobuhigashiuraowariasahiinuyamatobishimaiwakurashitarainazawatoyonegamagorimihamatoyotataharakariyayatomioguchikomakimiyoshinishiotokonamekiyosuchiryutoyohashiokazakiisshikikasugaikotakiratoeianjotogofusosetohazutsushimashinshirotakahamanisshinshikatsuhekinantoyokawaichinomiyatoyoakeodateogataakitaikawakyowahonjoogayurihonjonoshirokamiokakatagamimitanegojomeyokotekosakadaisenkazunonikahohonjyomoriyoshimisatohappoukamikoanihachirogatahigashinarusesembokufujisatokitaakitaitayanagiowanitakkomutsutsurutahirosakigonoheoirasetowadamisawanohejiaomorishingohiranairokunohehashikamitsugarushichinohehachinohenakadomarisannohekuroishisakaeisumiasahiotakiinzaiabikomatsudoyachiyomutsuzawakujukuriomigawakashiwatoganemihamanaritasakuranagaramobarahanamigawachoshishiroichoseikozakishisuikatorimidorichonankyonanfuttsuonjukufunabashinagareyamanodasosatakochuotohnoshourayasukimitsuyokaichibayotsukaidosodegauratateyamakamagayayokoshibahikariyachimatakatsuuratomisatokisarazukamogawaichikawanarashinoichinomiyashimofusaminamibososhirakoichiharaoamishirasatoikatahonaiainansaijoseiyoiyoozuuwajimaniihamanamikatamasakiuchikokihokutobetoonshikokuchuomatsuyamaimabarikamijimakumakogenyawatahamamatsunosabaeikedaobamasakaifukuiohionotsurugamihamawakasaminamiechizeneiheijikatsuyamatakahamaechizensoedaukihaomutaokawanishiogoribuzenonojosueumiokiotochikugosasagurisaigawamizumakishinyoshitomikurumekurateyamadakasuganakamamiyamanogatatakatahakataiizukakawaratagawakasuyaashiyainatsukimunakataminamitsuikishonaikurogifukuchikeisenhigashimiyakoshinguyukuhashiokagakiyamekogaongausuikahotohochuotoyotsumiyawakadazaifuhisayamatachiaraiyanagawanakagawahirokawachikujochikushinochikuhochikuzennamieotamaokumashowateneiiwakikoorinangoononishigoshimogoomotegomishimafukushimaasakawakagamiishishirakawaiitatefutabahiratayugawahanawakitakatakawamatakunimiyabukibandaihigashihironoyamatomiharuyamatsuriaizubangedatesomaaizuwakamatsuyanaizuaizumisatonishiaizuizumizakikitashiobarataishinkaneyamakoriyamainawashirotanagurafurudonosamegawasukagawaishikawatamakawaikedaogakitaruiginanenahashimahichisonakatsugawaibigawashirakawamizunamiminokamomitakekawauesekigaharatomikasakahogikitagatayamagatatajimianpachimotosuyaotsukakamigaharahidakanisekitokigujominogodoyorogifukasamatsutakayamawanouchihigashishirakawakasaharashimonitatsumagoichiyodakannakanrashowameiwakiryuotaoratomiokafujiokaitakuranaganoharahigashiagatsumatakasakishibukawaminakamikatashinatsukiyonokawabanumataannakaoizumimidorishintoisesakiuenoyoshiokakusatsutakayamanakanojonanmokutamamuratatebayashimaebashiotakekaitadaiwahongofuchukuietajimashobaramiharahatsukaichihigashihiroshimamiyoshikumanokurenakasakaseraseranishiasaminamifukuyamashinichionomichiosakikamijimajinsekikogentakeharaotobenanaeikedatohmaozoraobiraabirakyowaeniwataikibibaisharirebunerimohiroooketootarupippunishiokoppechitosefurubirahakodateshiranukakitahiroshimakushiroobihironanporoiwamizawaniikappukunneppufukushimanakasatsunaitoyourakuromatsunaiakabirakamisunagawashibechaurakawakamifuranonakatombetsuasahikawashimokawakayabeokoppebiratoriabashirisaromaatsumanumatahidakabifukamukawamikasahorokanaitoyotomisarufutsuhigashikawaishikarikitamiyoichiesashiiwanaitomariminamifuranoakkeshifuranotoyakoyakumootoineppushikaoishiraoinemuronayorohaboroashorobihororishirifujiutashinaihokutotakasuebetsuurausuassabukikonaishimamakinaiedatetoyabieinikiesanuryuoumuteshikagarikubetsuashibetsukimobetsuaibetsutobetsusobetsuembetsushimizuchippubetsurishirihokuryuhoronobeshintokutsubetsushibetsuhonbetsumombetsutsukigatakuriyamakoshimizushiriuchikutchanmurorannoboribetsukamishihorowassamushinshinotsukembuchiwakkanaikamoenaikiyosatotakinoueshikabesunagawafukagawanakagawatakikawakamikawahigashikagurahamatonbetsumatsumaemoseushirankoshishakotanimakanemashikeotofuketomakomaisandatambaitamiawajikasaiasagoshisoonoakoyashirotoyookaminamiawajiinagawafukusakitakasagokamigorikasugaharimayokawaashiyahimejiakashitaishiaogakisannantakinosumototakarazukanishinomiyashingugoshikinishiwakiyokatakaaioimikisayoyabukawanishiamagasakisasayamashinonsenkakogawaichikawakamikawatatsunotsukubaiwamaogawaasahisakaitokaioaraiitakobandodaigosuifuinaamikasumigaurakashimaomitamayachiyoshimodatetomobetoridehitachinakainashikisakuragawakasamayawaramoriyahitachiomiyanamegatayamagatahitachikamisuushikutakahagiibarakitonekoganakasowayukimihojosomitoryugasakishimotsumafujishirotsuchiurachikuseihitachiotashirosatotamatsukuriuchiharashikahakuinanaotsubatawajimakahokukawakitatsurugikaganominotosuzuuchinadakomatsuanamizunakanotohakusannonoichikanazawaiwateshiwafudaikawaimoriokaofunatohanamakikuzumakikitakamininohekunoheyamadayahabasumitaichinosekitanohatahiraizumirikuzentakatajobojiotsuchihironomiyakoiwaizumikarumaiichinohenodakujitonooshushizukuishifujisawamizusawakamaishikanegasakimannoutazukotohiraayagawazentsujihigashikagawauchinomikanonjisanukimarugamemitoyotakamatsutadotsunaoshimatonoshoakuneamamiizumihiokiyusuikinkoisasookouyamanakatanekagoshimakanoyaisenkawanabeminamitanemakurazakitarumizunishinoomotematsumotosatsumasendaioimatsudaayaseebinamiurazushinakaiodawaraiseharasagamiharahakoneaikawakaiseiatsugitsukuihadanoyamatoyamakitazamaoisochigasakininomiyayokosukakamakuraminamiashigarafujisawasamukawakiyokawahiratsukayugawaraokawaumajikochitsunootoyoakiinonishitosayasudahidakamiharasakawaniyodogawahigashitsunokagamigeiseisusakiotsukinaharisukumomurototosakamiochitoyotosashimizumotoyamanankokunakamurakitagawayusuharaogunichoyoukiasoutoozugyokutoamakusamifunetakamoriyamagaminamataminamiogunikikuchisumotoyamatonagasumashikiaraokumamotokamiamakusanishiharayatsushiroayabeseikasakyoideineujinakagyokameokakyotangokyotanabekyotambaminamiyamashiroyamashinatanabeyawatawazukaminaminantanmiyazuhigashiyamafukuchiyamakitamukokamojoyokizumaizuruujitawaraoyamazakinagaokakyokumiyamakawagoeinabeshimameiwaasahitaikiudonoisetsukisosakikuwanamihamamiyamasuzukatamakimisuginabarikumanokomonominamiisewataraitobakiwatakikihotadomatsusakayokkaichikameyamaureshinoishinomakishichikashukuohirataiwaosakizaohigashimatsushimashikamaiwanumashibataogawaraonagawakawasakiseminemarumoriminamisanrikukakudamuratawakuyatomiyanatoriwataritagajomisatotomekamirifushiroishimatsushimayamamotoshiogamafurukawahyugaebinotsunosaitoayakushimanobeokakitauramiyazakitakazakigokaseshiibamimatashintomikunitomikitakatakobayashikawaminamitakaharukijotakanabemiyakonojonishimeranichinankitagawakadogawamorotsukakisofukushimaminamimakisakaeobuseikedaogawamiasaokayaasahiotakiotarichinoinaomichikumakomaganechikuhokukaruizawayasuokaooshikaikusakaminamiaikitogakushimatsukawakawakamitateshinatakamorikitaaikishiojirimiyadahakubaiizunaiijimaiiyamamiyotasuzakayasakatoguraookuwanagawaminowahirayayamagataminamiminowafujimiomachisakakitakaginaganonakanosakuhokomoronagisoshinanomachiwadauedaiidaharasuwatomiachiaokianankisosakunozawaonsenagematsutakayamashimosuwamatsumotoyamanouchinakagawamochizukiazuminotatsunoobamaomuraseihiunzenosetofutsuikichijiwanagasakiisahayahasamisaikaikawatanasasebohiradokuchinotsugototogitsutsushimashimabarashinkamigotomatsuurayamazoekashibaikomakawaitenrioyodosangokoryoudaojiikarugayamatokoriyamatenkawakatsuragikurotakikawakamimiyakemitsuetakatorikamikitayamayamatotakadahegurishinjokanmakisakuraitawaramotogoseoudanarasoniandokawanishishimoichihigashiyoshinokashiharashimokitayamanosegawayoshinomintsivorytopazsakuragehirnsumomoaseinetopalmail-boxmokurenyoitamuikaojiyagosensanjoaganomyokoseiroagaomishibataniigatanagaokamurakamiuonumayuzawakariwatagamitainaitsunanminamiuonumatochioyahikojoetsuseiroukamosadoizumozakitokamachiitoigawasekikawakashiwazakitsubamemitsukekokonoesaikiusukibeppuusahimeshimakunisakihasamataketatsukumihitaoitahijikusuyufukujukamitsuebungoonobungotakadaibaraniimibizentsuyamaokayamakasaokahayashimayakagemaniwaakaiwamisakishinjotamanotakahashikibichuowakesojanagishookumenannishiawakurakurashikiasakuchisetouchikagaminosatoshotomigusukunakagusukuyaeseizenaurumaiheyaaguniogiminanjokinminamidaitokitanakagusukuyonaguniokinawaishigakikunigamiurasoekadenataramahiraraginozataketomishimojizamamitonakiitomanhigashimotobuyonabarugushikamionnanahanagohaebarukumejimakitadaitonakijinnishiharayomitanginowantokashikiishikawaikedasuitaminohizuminishisakaikananabenodaitoosakasayamayaokishiwadatadaokakaizukatondabayashichihayaakasakakumatorikadomasayamahigashiosakashijonawatehirakatataishimisakitajirihannansennankatanotoyonominatosettsuhigashiyodogawaibarakinosekitachuohigashisumiyoshifujiiderakashiwaraizumiotsutoyonakamatsubaramoriguchiizumisanoshimamototakatsukineyagawahabikinotakaishikawachinaganoyoshinogarikamiminearitaouchiimarihizenogikashimaariakekiyamafukudomikitagatakitahataomachigenkaikanzakinishiaritakyuragisagataratosutakushiroishikaratsuhamatamakouhokukawagoeyoshidasatteogoseirumaasakaurawaogawaniizaomiyayoriiotakishikihonjooganohannohanyuinasaitamaokegawaarakawayoshikawayokozehasudasayamahidakafukayachichibuiwatsukiryokamiyoshimikamiizumifujimiwarabiranzanmiyoshiminanoyashiosakadosugitomisatohigashichichibutodasokakukiyonokazoshiraokakasukabekounosukawajimatsurugashimamiyashirokitamotohatoyamamoroyamahatogayakumagayakawaguchinagatorokamisatomatsubushinamegawatokigawakamikawafujiminohigashimatsuyamakoshigayatokorozawas3isk01isk02ryuohkoseikonanaishorittotakashimamaibarahikonetorahimenishiazaikokagamokotoyasuotsukusatsunagahamamoriyamatoyosatotakatsukinotogawaomihachimanhigashiomiakagiunnanizumogotsuamayatsukakakinokimatsuehamadamasudahikawahikimiokuizumoyasugiyakumomisatotamayuohdahigashiizumookinoshimanishinoshimatsuwanoshimaneshimadafujiedayoshidashimodagotembaiwataatamikosaiyaizuitoizumishimahaibaramakinoharaomaezakikawanehonkannamisusonohigashiizufukuroinumazukawazufujiaraishizuokahamamatsushimizuizunokunimatsuzakimorimachiminamiizunishiizukikugawakakegawafujikawafujinomiyaujiietsugaoyamayaitaohiranikkoashikagakuroisokanumasakurashioyakarasuyamamotegiichikaikaminokawatochigihagamokanogisanobatonasumibunasushiobaranishikatautsunomiyaiwafunemashikoshimotsukeohtawaratakanezawaitanokomatsushimatokushimaichibaminamiaizumiwajikikainanmiyoshinarutomimamugiananmatsushigesanagochishishikuinakagawamachidachiyodakomaefussainagitaitochofufuchuomeotahigashiyamatotoshimaokutamaaogashimakodairaedogawaarakawahachiojishinagawatachikawashibuyasuginamihinodekiyosesumidaoshimanerimamitakahamuraadachinakanomizuhobunkyomegurominatokoganeihigashikurumekokubunjihigashimurayamamusashimurayamatamakitahinochuokotokatsushikakouzushimaogasawaraakishimakunitachishinjukusetagayamusashinohachijoitabashiakirunohinoharachizunanbukotouramisasawakasayonagokogehinoyazutottorinichinansakaiminatokawaharaoyabetairainamiasahinantoimizufuchutakaokakurobeyamadajohanatoyamatonaminyuzenfunahashinakaniikawanamerikawaunazukitogahimiuozufukumitsutateyamakamiichiiwadearidayuasainamitaijikatsuragiaridagawatanabemihamahidakakainankiminomisatoshingushirahamakamitondayurakozakoyagobokitayamawakayamakudoyamahashimotokushimotokozagawahirogawakinokawanachikatsuurarsuseroeoishidasagaeoguniasahinagaitendonanyoobanazawanishikawasakataohkuratozawamikawamamurogawayamagatafunagatatakahatashonaishinjokahokuiideyuzakawanishitsuruokakaminoyamayamanobeshiratakamurayamanakayamakaneyamahigashineyonezawasakegawamitouubeyuuabushimonosekitabuseoshimatoyotaiwakunihikarishunannagatohagihofukudamatsutokuyamashowadoshitsurunanbukoshukaiminami-alpsnirasakikosugeotsukioshinohokutominobuyamanashifuefukichuokofuichikawamisatoyamanakakonakamichitabayamanishikatsuranarusawafujikawahayakawafujiyoshidafujikawaguchikouenohara長野京都岐阜大阪三重群馬千葉滋賀佐賀奈良adednelgaccogogror秋田愛知高知埼玉沖縄栃木熊本岩手青森山梨新潟島根鳥取長崎香川宮城石川大分宮崎茨城山口兵庫山形徳島広島福島福岡岡山富山静岡愛媛福井東京xn--4it168dhatenadiaryxn--vgu402ckawaiishophatenablogcocottenamaste北海道penneehimeiwateversestabachibashigagonnagunmapermahaccaakitaosakauh-ohblushkochiaichifukuikuroncapooitigohyogotokyokyotopunyuthickcheap0t00g00j0mie2-ddaapyawjg0amfemsubxiiboomoobutchueekpgwrgrherskrboyrdyupperunderflierchipsmydnsheavyangryhippygirlyrulez神奈川鹿児島和歌山bambinaxn--nit225kokayamasaitamaxn--k7yn95exn--1lqs03nsapporoparasitelolipopmcxn--efvn9sniigatafukuokatokushimafukushimahiroshimakagoshimafakefurokinawaxn--8pvr4ucoolblogxn--0trq7p7nnkawasakinagasakimiyazakichilloutxn--8ltr62kxn--klty5xpeeweezombiecutegirlxn--rny31hxn--uuwu58axn--ntso0iqx3axn--djrs72d6uytoyamanikitanyantakagawamimozanagoyaboyfriendxn--2m4a15egreaterchowderegoismyamagatafashionstorexn--elqq16hxn--pssu33lsendaimiyagixn--rht27zpecoriaomorisaloonwatsonvivianxn--djty4knobushipigboatnaganopinokoxn--f6qx53asadistvelvetsecretxn--5js045dchicappayamanashiibarakidigickgirlfriendxn--1lqs71dmongolianxn--c3s14mxn--qqqt11mtochigixn--5rtq34kparallelo0o0mondkobesagabonadecaoitanarafoolkilldecimainhiholomosblokilociaoundopupugifutankcrapflopnooroopsmodsholyjeezstripperpepperbittershizuokaxn--rht3dkitakyushureadymadeicurusversusmatrixxn--rht61ehungryfloppygloomycrankyhandcraftedlittlestarxn--klt787dxn--kltx9awhitesnowsunnydaytottorilovepoptheshopbuyshopxn--5rtp49cxn--d5qv7z876cwebaccelxn--kbrq7oxn--4pvxsxn--1ctwolovesickkumamotocatfoodxn--tor131oyokohamawakayamatonkotsuxn--ehqz56nxn--uist22hxn--6btw5axn--kltp7dyamaguchifrenchkisspussycatxn--4it797kxn--uisz3gbabybluexn--zbx025dnetgamersxn--7t0a264ckanagawaxn--6orx2rishikawaxn--ntsq17ghalfmoonschoolbusjellybeanxn--mkru45iusercontentlolitapunkxn--32vp30hsakurastoragehokkaidoshimanecandypopbabymilksupersaleweblikeraindropbackdropwebsozaikikirarahateblodaynightmeneacsccogoormobiinfoaeusxxorgmilcomnetedugovorgcomnetedugovbizinfotmprdorgmilcomnomedugovassnotairespresseassocoopgouvveterinairemedecinpharmaciensorgnetedugovtraorgcomedurepgovmeneperekgacscaiiocogoitoresmshsseoulbusanulsandaeguc01milvkimmvchungnamjeonnamjeonbukeliv-dnsgyeonggijejueliv-cdnincheondaejeongangwongyeongbukgwangjuchungbukgyeongnameliv-apicoeduindorgcomembnetedugovorgmilcomnetedugovjcloudorgcomnetintedugovperbnrinfocooyorgcomnetedugovethipfscanvamypepethw3sstorachakeeneticjoinmcinbrowserdwebcyonnftstoragemyfritzaemewphlxachotelltdorgcomwebsocschngonetintedugrpgovassnomgacsccoorgnetedugovbizinfo123websiteidorgmilcomasnnetedugovconfidmedorgcomplcschnetedugovaccoorgnetgovpresstmassoirseproxaccosoundcasthoptocraftvp4c66orgnetedugovitsmcdirmyboxbarsyedgestacksynologylogintoopencloudnohostwebhopdiskstationi234tcp4hoocgroknoipprivmydsddnsdnsforlohmustransipdscloudfilegear-sgbrasiliafilegearframerbarsybarsyonlinecoprdorgmilcomnomedugovinforgcomnetedugovnameacprorgcomartnetedugovpresseinfoassoinstgouvorgnycedugovbarsydscloudjuorgcomnetedugovminisiteaccoororgcomnetgovorgmilcompronetintedugovbizmuseumnameinfoaerocoopaccoorgcomnetintedugovbizcooporgcomgobneteduorgmilcomnetedugovbiznameaccoorgmilneteduadvgovcoorgcomnetaltgovforgotherhiskeeneticispmanagernomassoprod5476132eastasiacentraluswesteuropewestus2eastus2pnortheurope-01newzealandnorth-01southindia-01southcentralus2-01norwaywest-01eastus2-01westus2-01australiaeast-01italynorth-01israelnorthwest-01swedencentral-01westeurope-01centraluseuap-01taiwannorthwest-01uaecentral-01northcentralusstage-01israelcentral-01mexicocentral-01canadacentral-01austriaeast-01germanywestcentral-01francecentral-01ukwest-01denmarkeast-01polandcentral-01eastus-01westus-01swedensouth-01eastus3-01westus3-01brazilsouth-01centralus-01francesouth-01australiacentral-01westindia-01uaenorth-01jioindiacentral-01canadaeast-01belgiumcentral-01spaincentral-01koreacentral-01chilecentral-01qatarcentral-01westcentralus-01eastus2euap-01norwayeast-01southafricanorth-01brazilsoutheast-01germanynorth-01switzerlandnorth-01switzerlandwest-01japanwest-01southafricawest-01japaneast-01eastasia-01indiasouthcentral-01taiwannorth-01centralindia-01uksouth-01southcentralus-01northcentralus-01eastasiastage-01indonesiacentral-01australiacentral2-01australiasoutheast-01malaysiawest-01koreasouth-01southeastasia-01southeastus5-01northeastus5-01jioindiawest-01rucdnwest1-usfra1-desandboxjls-sto1jls-sto3jls-sto2aglobalabglobalsslmapprodfreetlsmapvpslon-1lon-2ny-1fr-1sg-1ny-2paassnwebpaashostingjelasticnordeste-idcsocuserpagescwebfileblobservicebuscoreatlricnjsjelasticwebsitestoragesezagbinruhuukjptsmyspreadshopmynetnameakamaiorigin-stagingfrom-coipv64dynv6cdn77serveblogadobeaemcloudhicamsprytdnsupno-ipownipde5ovhicpfirewall-gatewaysytesmypsxbarsyusgovcloudapimyamazemyradwebakamaihdsaveincloudfastlylbfrom-lasubsc-paysquare7in-the-bandblackbaudcdnhomelinuxoninfernoctfcloudservebbsdns-dynamiccloudfrontakamai-stagingipifonyham-radio-opsenseeringclickrisingcommunity-profrom-nylocalcertgrafana-devedgesuite-stagingcloudflareanycasteating-organicatlassian-devmydattofeste-iplocaltotorprojectknx-serveredgekeycloudflareglobalcloudyclustercasacamserveftpakamaized-stagingakamaiorigindns-cloudmyeffectboomlabotdashbuyshousestwmailhetemlazure-mobilein-dslthruhereredirectmedynuddnsbouncemesupabaseluyanicloudappakamaicloudfunctionsdebiannhlfanpgafanstatic-accessin-vpnmysynologymafeloappudohomeftptrafficmanagersiteleafseidatmemsetcloudflarecloudaccesskeyword-onazure-apiis-a-chefdoes-itgets-itwebhopselfiphomeipkicks-assedgesuitewindowsserver-ontunnelmolemydissentscrapper-sitecloudflarecnuni5srcfggffiobbzabchrsndenodynuopikddnsvpndnsakadnselastxkinghostvps-hostfastlyhomeunixazureedgeshopselectdontexistmyfritzcloudjiffyalwaysdatasells-itsquaresbroke-itazurefddattolocalat-band-campmeinforumfamilydsazurestaticappsdefinimabplaceddnsaliasdynaliasnow-dnsblogdnsroutingthecloudendofinternetdsmynasakamaiedgemymediapcadobeio-staticakamaiedge-stagingakamaihd-stagingddns-ipprivatizehealthinsurancelive-onkrellianschokokeksmassivegridmysecuritycamerarackmazeserveminecraftfrom-azis-a-geekakamaizedmoonscaleoffice-on-theusgovtrafficmanageradobeioruntimeedgekey-stagingreserve-onlinechannelsdvrdnsdojousgovcloudappcdn77-sslapps-1and1podzoneazurewebsitesdynathomescaleforceyandexcloudvusercontentisa-geekcdn-edgescoaemalcesappwriteazimuthtlonarvobuiltwithrocketnoticeablestorecomwebrecnetperotherfirminfoartslgdloncogoiltdorgmilcolcomplcschgenngonetedugovbiznamefirmmobiacincoorgmilcomnomwebgobnetintedubizinfocomyspreadshopdemongovtransurl123websitehosting-clusterkhplaycistrongsnesosvalervålerxn--vler-qoaossandeheroysandeherøybøboheroyherøyxn--hery-iraxn--b-5gavalerbøboxn--b-5gasandesandexn--hery-iraxn--vler-qoavålerhåreålaahavaofsfvfhlolnlalrlhmfmtmahcostntbuåstrmreigersundmyspreadshopgálsáeidsvolltingvollgildeskalflorøvadsøvardøvanylvenxn--bhccavuotna-k7astrandaxn--kvnangen-k0axn--sknland-fxaxn--mosjen-eyarakkestadhyllestadnannestadvevelstadvaapstenordre-landsondre-landsøndre-landtjieltexn--vrggt-xqadsør-aurdalsor-aurdalheradstordmoldefordeførdeseljefedjeryggehemnexn--krehamn-dxasognegranesøgnebrynetjomevallebykletokkegiskedovretjømehobølvoldasaudatolgasømnaviknadønnasomnadonnatranafrananesnaraumasmolatrænafrænalesjasmølaørstaorstahitrafloraaukraloppafrøyarissasnasahalsagalsaromsaraisaráisafroyasnåsagronghobolfjelltydalårdalardalaskimharamkraanghkekråanghkesorumbarumhurumbærumsørummodumsálátbálátfrognbjugnvåganvagangulenskienløtenlotenstrynvefsnxn--merker-kuaskaunsveiobømlobomloskjåkvardoflorovadsosalatbalatsálatklæbuklabuselbubarduulvikskjakklepprisørxn--nttery-byaeflåeidflahofmilgolholsellomskifetvikdepvgsfhsaskerrisorhamarasnesåsnesrørosrorosxn--slat-5namasoynaroyvaroyluroydyroyaskoyradoyandoyrodoymeloyradøyandøyrødøymeløyaskøylurøydyrøymåsøyværøynærøyhoylandethøylandetdivtasvuodnalørenskoglorenskognesoddtangenxn--tjme-hraxn--smla-hraxn--stjrdal-s1aunjargalillehammerunjárgaxn--hamary-fyadavvenjargaxn--bearalvhki-y4a123hjemmesidegjerdrumxn--brnnysund-m8acxn--tnsberg-q1axn--mlatvuopmi-s4axn--snsa-roaxn--skierv-utaxn--brum-voatysfjordkvafjordeidfjordkvæfjordsongdalenmjondalenmjøndalenxn--gls-elackragerogáŋgaviikagangaviikasørreisasorreisasør-varangersor-varangerxn--risr-iraskiervaxn--frna-woaxn--trna-woakvinesdalleksvikleirvikrøyrvikroyrviksvelvikvenneslaevje-og-hornnessandnessjøenmarnardalvindafjordsandefjordenebakksnillfjordullensvangxn--trany-yuabrønnøysundnamsskoganaustevollxn--stjrdalshalsen-sqbnord-aurdalnord-frontrøgstadtrogstadgrimstadflakstadgjerstadxn--sandy-yuaxn--leagaviika-52bnore-og-uvdalvegarsheixn--rlingen-mxaxn--ggaviika-8ya47hvegårsheikarlsoykvitsoymasfjordenhamaroyinderoyosteroydavvenjárgasauheradguovdageaidnuxn--vre-eiker-k8abronnoysiellakkrødsheradkrodsheradkvinnheradbrønnøyxn--mtta-vrjjat-k7afxn--lrenskog-54akvitsøyvárggátkarlsøyosterøyinderøyhamarøybronnoysundxn--aurskog-hland-jnbbahccavuotnabáhccavuotnagiehtavuoatnastor-elvdalmidtre-gauldalxn--gildeskl-g0akarasjokevenassixn--bievt-0qaxn--yer-znalebesbynessebyxn--hbmer-xqamalselvmålselvxn--unjrga-rtamøre-og-romsdalmore-og-romsdalhareidmelandørlandorlandstrandålgårdsolundalgardafjordåfjorddielddanuorrikautokeinoxn--stre-toten-zcbskodjeaejriestangeliernebamblestokkefauskesnåasesnaasekongsvingerlangevagberlevagxn--flor-jrahattfjelldalostre-totenøstre-totenvestfoldxn--mely-iraálaheadjualaheadjunordreisaxn--troms-zuaxn--lgrd-poacporsangerflatangerstavangerleikangerbremangersamnangergieldakarasjohkaxn--rdy-0nabfrostautsirasnoasatromsaxn--sr-aurdal-l8aflekkefjordjølsterjolsteraremarkhedmarknååmesjevuemienaamesjevuemiexn--vard-jrarollagmeråkermerakerorskogørskogxn--bdddj-mrabdákŋoluoktaxn--osyro-wuaaknoluoktatrysilskjervøymandaljondalbindalrindalmeldalsuldalorkdalsigdalalvdallærdalhurdalsirdalverdallerdallardaloppdalåseralaseralhadselkragerødivttasvuotnaoverhallasteinkjerxn--hnefoss-q1askedsmokorsettromsøxn--dyry-iravestre-totenmuseumxn--sandnessjen-ogbrahkkeravjufylkesbiblbájddarbajddarxn--laheadju-7yarennesøyxn--koluokta-7ya57hxn--hgebostad-g3aleirfjordstorfjordbalsfjordbåtsfjordbatsfjordmuosátbievátloabátkárášjohkanøtterøyxn--mjndalen-64anordkappláhppilahppialstahaugsiljanverranrøykenroykenhaldenlyngenbergenhortenhønefosshonefosstroandinbeiarnvarggatosoyroosøyrotromsoidrettmuosatbievatruovatloabatvoagattynsetnessetxn--indery-fyaskánitskanitraholtråholtxn--ystre-slidre-ujbandebusarpsborgbearduxn--karlsy-fyahordalandjorpelandjørpelanddeatnuringsakersør-odalsor-odalxn--slt-elabringerikeaudnedalnittedalnissedalhemsedalslattumsurnadalxn--blt-elabelverumstjørdalnaustdalhjartdalgjøvikfyresdalhasviknarviklarvikgjovikmalvikgamviklenvikporsgrunnstjordalengerdaldrobakdrøbakxn--msy-ula0hvestvagoyxn--vgan-qoaxn--ryken-vuaxn--lten-graxn--stfold-9xaxn--hpmir-xqaxn--lury-iramálatvuopmimalatvuopmitysværkirkenesbirkenesmoskenesbáidárxn--fjord-lraxn--rdal-poabahcavuotnabáhcavuotnaxn--frde-gralindåsbearalvahkixn--hobl-iraráhkkerávjuxn--loabt-0qavågåáltábodøsundlundraderådeetnetimeholeauregrueoddavagavegaranatanaarnasolasulaaltalekafusavangbergkvamåmliamlibokntinnroangranosenoslobodorøstroststatåmotamotivguprivøyeroyerliermossvossxn--nvuotna-hwalusterlunnermarkerhábmerhabmerhvalerfjalerxn--rholt-mratysvarbaidarfitjargaularhápmirhapmirmelhusfosnesøksnesoksnestysneshemnesevenesflesbergeidsbergtonsbergtønsberglindasxn--sndre-land-0cbnamsosxn--srum-graøystre-slidreoystre-slidrevestre-slidretrondheimbalestrandxn--langevg-jxaaustrheimxn--skjk-soavagsoyaveroysandoykarmoyfinnoytranoyvestbytranbysykkylvenxn--hyanger-q1aspjelkavikandasuoloxn--fl-ziaxn--drbak-wuastathellexn--sr-varanger-ggbtelemarkxn--bhcavuotna-s4axn--porsgu-sta26fčáhcesuolocahcesuoloakrehamnåkrehamnsandøykarmøyfinnøytranøyvågsøyaverøynamdalseidxn--lesund-huabadaddjaxn--vegrshei-c0axn--btsfjord-9zagildeskålporsanguxn--trgstad-r1anávuotnanavuotnahammerfestxn--sgne-graxn--brnny-wuacibestadharstadnarviikaevenáššivestnesgjemnessandnesagdenesrennesoyxn--avery-yuaxn--tysvr-vrabearalváhkikongsbergspydebergrandabergxn--andy-iradavvesiidaxn--krdsherad-m8aporsáŋgufredrikstadbjerkreimringeburennebuaurskog-holandnotteroyxn--vgsy-qoa0jxn--rmskog-byaskierváivelandbyglandfrolandaurlandforsandxn--bjddar-ptamidsundålesundalesundfetsundfarsundovre-eikerøvre-eikerakershusxn--moreke-juasørfoldøstfoldostfoldsorfoldhøyangerhoyangerlevangerorkangertanangerxn--vestvgy-ixa6olillesandulsteinxn--rennesy-v1agranvinskjervoyxn--klbu-woalavagisxn--h-2faxn--ryrvik-byakafjordkåfjordseljordfolkebiblxn--gjvik-wuajevnakerxn--kfjord-iuabudejjuxn--kranghke-b0axn--davvenjrga-y4axn--rland-uuaxn--ldingen-q1axn--mlselv-iuaxn--rady-iraxn--linds-prabrumunddalxn--ygarden-p1amo-i-ranaeidskogrømskogromskoghjelmelandxn--finny-yuaxn--sr-odal-q1axn--skjervy-v1aballangenkvanangenkvænangengratangenxn--hmmrfeasta-s4acvossevangensuohkanxn--rde-ulaxn--mli-tlaxn--ksnes-uuanordlandskanlandskånlandsortlandfuoiskuxn--rros-graxn--hcesuolo-7ya35bxn--eveni-0qa01gagaivuotnagáivuotnaxn--seral-lradrammenmodalenmosjoenjan-mayentorskensteigengloppenxn--snes-poamatta-varjjatxn--sr-fron-q1aomasvuotnajessheimbådåddjåxn--krager-gyaxn--kvfjord-nxaxn--asky-iraxn--snase-nraxn--bidr-5nacholtålenxn--vads-jraxn--jlster-byamosjøenxn--rst-0nastavernxn--ostery-fyaxn--oppegrd-ixaxn--sknit-yqaxn--risa-5naoppegårdskiptvetrendalenholtalenxn--mot-tlaxn--lhppi-xqaxn--holtlen-hxaxn--srreisa-q1akopervikxn--muost-0qaxn--bmlo-grahokksundkvalsundegersundxn--karmy-yuaullensakerxn--hylandet-54axn--kvitsy-fyaxn--bod-2nalangevågberlevågkristiansandxn--rsta-frahornindalstjørdalshalsenstjordalshalsensandnessjoenhámmárfeastaxn--lrdal-srasør-fronsor-fronnord-odalkristiansundmátta-várjjatvestvågøynesoddennotoddenbuskerudøygardenoygardensalangenlavangenralingenrælingenlodingenlødingenleaŋgaviikalaakesvuemieleangaviikauenorgexn--srfold-byaaskvollxn--rskog-uuaxn--nry-yla5gxn--vry-yla5ghammarfeastaxn--rhkkervju-01afxn--givuotna-8yakommunekrokstadelvanedre-eikerhagebostadhægebostadxn--berlevg-jxakviteseidxn--s-1faxn--l-1faxn--nmesjevuemie-tcbafuosskomoårekemoarekexn--lt-liacxn--jrpeland-54asvalbardoppegardholmestrandtvedestrandsogndalsokndalarendalsunndalfolldalxn--krjohka-hwab49jlyngdaletnedalnorddalsaltdalgausdalskedsmovaksdalgjesdalstordalxn--frya-hraaarbortedrangedalxn--smna-graaurskog-hølandxn--vg-yiabtjeldsundhaugesundlindesnesxn--mre-og-romsdal-qqbxn--dnna-gradyntmpheremerseineshacknetenterprisecloudmineaccomaorimāoriorgmilcriiwigennetschoolhealthkiwigovtgeekxn--mori-qsacloudnsparliamentcomedorgcompronetedugovmuseumwebsitekinservicebarsywebsitebuildereerobookheimdnsleapcelleero-stagetechcrscsslorigingohomecdbedeeeiemesecabgngilnlalplchfisiincnnoroptatitmtltruauhulumkdkukskjplvtrgrfrkrhrusesismycynzcznetinteduassoososcloudstgbetaaezaeuhkusjshatenadiarycdn77hoptozaptois-a-knightmyftpno-ipjpnddnssdpdnsspdnsbarsysweetpepperis-a-bruinsfanis-very-sweetservegameis-a-soxfanhomelinuxcdn77-secureservebbsmisconfusedwebredirectblogsitefreedesktopcouchpotatofriestoolforgeaccesscamis-lostreadmyblogsmall-webfedorapeopleserveftpis-a-celticsfanmywirepotagertwmailin-dslsellsyourhomeread-booksfreeddnscable-modemis-savednflfanufcfanmlbfanstuff-4-saleendoftheinternetin-vpnmy-firewallhomeftpis-localis-a-chefboldlygoingnowherewebhopselfipkicks-assroxatunkcamdvrfedoraprojectgotdnsdvrdnsdyndnspubtlspimientahomeunixdontexistfedorainfracloudwmflabsfspagesbmoattachmentsteckidsfamilydsdnsaliasdynaliasnow-dnscloudnsdoomdnsduckdnsblogdnshomednsroutingthecloudendofinternetdsmynasip-dynamicpoivronhttpbinmyfirewallis-very-evilmysecuritycamerais-a-linux-userwmcloudis-a-geektuxfamilyis-a-candidatedoesntexistis-very-badhobby-sitegame-hostaltervistais-foundis-a-patsfandnsdojohepforgepodzonedynservcollegefanis-very-goodfrom-meis-very-niceisa-geeknerdpolacmedsldingorgcomnomgobabonetedupleskaemhlxmyboxrockyprvcydeuxfleurspdnscodebergheyflowstatichostorgmilcomnomgobneteduorgcomeduiorgmilcomngonetedugovcloudns1337ngrokacorggogfamcomwebgobnetedugokgopgkpgovgosbizpasaugumicsopozpapuwmwsrprusiskwpspkppspkmpspokeoiawsawifoumsdnskokwpmuppuppsppiwwiwoowuzswkzoschrzpisdnwzmiuwwitdpssewsseumigugimoirmpinbwinbwiihupporzgwgriwupowwskrwioswuozstarostwokonsulattmpccopruszkowmyspreadshopostrodakartuzyopolegminamediaustkazgorajgoraolawailawalomzawloclradombytomjaworznotargilubinkoninzagantorunkutnokepnonakloczestsopotsanokturekplockslasksklepzarowlukowmedaidgdaorgmilrelcomnomatmgsmartneteduelkgovwawsossexbiztgorysejnytychypomorzeboleslawiechomesklepsdscloudunicloudzakopanelegnicarawa-mazbydgoszczswidnikkrasnikwloclawekbielawamragowograjeworealestatebeskidykaszubymalopolskaprzeworskswiebodzinlecznadfirmaszkolawarmiagdyniamiastakazimierz-dolnymalborkswidnicadlugolekaostrolekapodlasieelblagtravelsimplesitezachpomormielecszczecinnieruchomosciwalbrzychlezajsklublinbedzinpoznanwielunmielnooleckostarachowicedkontopowiatwroclawrybniksuwalkileborkslupskgdanskostrowwlkptarnobrzegtourismwegrowkrakowglogowyou2pilanysamailwrocinfoagroautobeepshopprivlapypiszlodzcfolksecommerce-shopmazurypulawyskoczowrzeszowpomorskiezgierzkaliszolkuszlowiczostrowiecsosnowiecmazowszewodzislawbialowiezazgorzeleckatowicepabianicejelenia-gorawolominkarpaczsieradznowarudaczeladzkonskowolaskierniewiceswinoujscieturystykabieszczadycieszynketrzynolsztynbialystokbabia-goraprochowicewarszawastalowa-wolapolkowicegorlicegliwiceponiatowalimanowalubartowaugustowkobierzyceopocznognieznoszczytnokolobrzegshoparenapodhalebielskoklodzkostargardatwithplayitownnamecoorgnetedugovacorgcomproestnetedugovbiznameislaprofinforechtngrokmedaaaacacpaenglawjurbarbarsykeeneticavocatacctcloudnsorgcomsecplonetedugov123paginaweborgcomnetintedugovnomepublidkinbarsygovx443cloudnsorgmilcomnetedugovcooporgmilcomschnetedugovnamecomcannetlibassoaemclantmcontstoreorgcomnomrecwwwbarsyfirminfoshopartsstackitmyddnswebspacelima-cityacincooxorgedugovbarsybrendlyhbvpsvpsspectrumlandinghostingacppmordoviamcprecbgorgmilcomspbnetintedumsknovgovbirrasmcdirmytismircloudvladimirnalchikadygeyamarinepyatigorskmyjinobashkiriaeurodirvladikavkazna4ugroznykustanaikalmykiacldmaildagestaniranbuildcloudcanvaliaravalwixdevelopmentappwritemigrationneedleverceldatabasestackitcodereplravendbonporterlovableaccoorgmilnetgovcoopmedorgcompubschnetedugovservicemecomygovorggovtvmedorgcomnetedugovinfoedgfacbmlonihkutwpsryxzbdtmacfhppmyspreadshopbrandpartiorgcomfhvpress123minsidaitcouldbeworlanbibkommunalforbundfhskiopsyskomvuxkomforbnaturbruksgymnloginlineorgcomnetedugovenscaledeuusentsurgebotdaorgmilcomnetgovnowteleporthashbangplatformlovablebarsyshopwarebasehoplixbarsyonlinemsf5gitappgitpagewawamscofigma-govcaffeinefigmacanvasoltstscwputerbarsysupportchatgptsquareomniweopensocialcpanelplaycodenotionnovecorewpsquaredpreviewjelecyonbyensrhtfastvpspieboxconvexjouwwebheyflowplatformshloginlinemadethissourcecraftclouderaorgorgcomartedugouvunivmeorgcomnetedugovsurveysstatichfheiyuxs4allprojectmyfastubervibehostapp-ionosdeployagentmecoorgcomschnetedugovbizcncostoreorgmilcomneteduembaixadaconsuladokiraranohoprincipesaotomeheliohobarsystorebaseshopwaresellfyaiabkhaziavologdamordoviapenzalenugsochinavoiexnetspbmsknovnorth-kazakhstanashgabadkareliaarmeniageorgiavladimirnalchikivanovobukharaadygeyakhakassiakalugakrasnodarjambylaktyubinsktroitskbryanskobninskkurganazerbaijanpokrovskbashkiriatselinogradvladikavkazmurmansktulatuvamangyshlaktashkentchimkentgroznykaragandatermezarkhangelskkustanaikalmykiabalashoveast-kazakhstankaracoldagestantogliattibarsyredorgcomgobedumirenknightpointaccoorgjelasticdiscoursecleverappsschacmiincogoornetonlineshopcogoorgmilcomwebnicnetintedugovbiznametestcoorgmilcomnomnetedugovorangecloudpersoindorgcomfinnatnetgovensmincomtourismintlinfox0611oyaorgmilcomnetedugovquickconnectvpnplusnettprequalifymeaddrmyaddrntdllwadlnctvavdrk12orgmilpolbeltelcomwebgennetedutskkepgovbbsbiznameinfocoorgmilcompronetedugovbiznameinfobetter-thanworse-thansakurafromdyndnson-the-webmymailerorgmilurlcomneteduidvgovmydnsgameclubebizmeneacsccogotvorhotelmilmobiinfovodteiflgplkmsmsbcckhincndnvncoztltmkckppzpdprvcvkvlvcrkrkscxuzchernovtsyrivneyaltaodesavolynrovnolutskltdinforgcomnetedugovbizvinnicazhitomirternopilpoltavakropyvnytskyizaporizhzhiasevastopolsebastopoluzhgoroduzhhorodkharkovkharkivvinnytsiakhmelnytskyizaporizhzhecrimeaodessazhytomyrnikolaevcherkassydonetskluganskluhanskkirovogradivano-frankivskchernivtsikrymkievkyivlvivsumyzakarpattiamykolaivcherkasychernigovkhersonchernihivdnipropetrovskdnepropetrovskkhmelnitskiyneacsccogoorusorgmilcomedugovmyspreadshopadimono-ipbarsybarsyonlinelayershiftnh-servretrosnubapicampaignservicelugaffinitylotteryweeklylotteryraffleentrygluglugsmeaccoindependent-inquestnimsitecopropymntltdorgplcschnetgovnhsbarsyindependent-commissionindependent-reviewpolicepublic-inquiryindependent-panelconnhospindependent-inquiryroyal-commissionoraclegovcloudappscck12libaws-govccphxcclibpvtparochchtrcck12libcceatonk12coglibtecgendstmusann-arborwashtenawcck12glghcck12sealibforksolympiabainbridge-islkeyporthoquiamyarrow-pointcentraliaport-townsendsequimport-ludlowrentonsilverdalebremertonredmondsheltonbellevueport-orchardport-angeleskingstonchehalisaberdeengig-harborseattlepoulsboidmdndsddemenegacalamaiavawapailalflnmdcncscohnhmihiviwiriinmntnmocoutvtctmtgunjokakwvnvprarorasmskstxwynykyazisadninsnngosrvis-bymircloudservernamepointtoenscaledland-4-salefreeddnsstuff-4-saleazure-apinoipdatabricksappscloudnsgolffanheliohostazurewebsitesgvorgmilcomgubneteducoorgcomnetd0egvorgmilcomnetedugovmydnsiacostoree12orgmilcomnomwebgobbibrectecnetintedugovraremprendefirminfoartseducok12orgcomnethidnsidacaiiosonlahanamhanoicamauhueorgcompronetintedugovbizbacninhtayninhhoabinhnamdinhtravinhhaiphongvinhlonghaiduongquangnamquangtrithuathienhuequangninhbacgianghaugiangquangbinhsoctrangbentrethanhphohochiminhdanangkontumhatinhkhanhhoathanhhoahealthgialailaocaiyenbaibackanngheanlonganphuyenphuthocanthodaklakdongnainameinfovinhphucdongthapkiengiangtiengiangquangngailaichaulangsonlamdongdaknonghagiangangiangcaobangbinhduongninhthuanbinhthuanbaclieuthaibinhninhbinhbinhdinhtuyenquanghungyenbaria-vungtauthainguyendienbienbinhphuocschbizputerimagine-proxyorgcomnetedugovcloud66advisormypetsdyndnsxn--8dbq2axn--4dbgdty6cxn--5dbhl8dxn--hebda8bxn--80auxn--d1atxn--c1avgxn--o1acxn--o1achxn--90azhxn--55qx5dxn--uc0atvxn--od0algxn--wcvs22dxn--gmqw5axn--mxtq1mxn--12c1fe0brxn--h3cuzk1dixn--12co0c3b4evaxn--12cfi8ixb8lxn--o3cyx2axn--m3ch0j3axn--j1adpxn--90amcxn--90a1afxn--h1ahnxn--j1ael8bxn--h1alizxn--c1avgxn--j1aefxn--80aaa0cvacxn--41acaffeineexeopentunnelbotdashtelebitorgtmaccoagricorgmilnomwebnicngonetaltedugovlawnisschoolgrondaraccoorgmilcomschnetedugovbizinfoprg1-zeropstritonstackitlimazeropsaccoorgmilgovяспборгкоммскбизмирсамаракрымсочиакодпроргобрупрצהלממשלישובאקדמיהองค์กรธุรกิจรัฐบาลศึกษาทหารเน็ต教育網絡組織公司政府個人닷넷한국澳门新闻澳門联通家電嘉里招聘通販닷컴삼성コムგეбгрфеюadcdbdgdidmdsdtdaebedeeegeiejekemenepereseveyegabacalamanauavapaqasazacfbfafgfnfpfwftfbgcgagggegkgngmgsgpgvgtgugilmlnlalclglplsltlhmimjmkmmmomambmcmdmfmgmzmpmsmtmgbbblbsbecccacnclcmcvctcscmhkhghchbhthphshlinikifigiaibicivisikninhnmncnbngnsnpnvntnjoionomobocoaofodorosotoptstttytatbtetgtithtmtltrusuvuaucueuguhulumunufjdjbjtjsjlkmkhkfkdkcktkukskpkgpmpnpkpjpgqaqmqiqsvtvcvbvmvlvrwpwtwzwbwcwawgwkwmwtrsrprgrfrercrbrarnrmrlrkrirhrwsusrssspsgsesbsaslsmsissxmxaxcxuypysylymykygybycyuztzsznzmzkzdzczbzazελευ世界台灣购物公益点看臺灣网络書籍在线网站手机机构大拿游戏信息台湾谷歌慈善商标香港中国餐厅网址中國商城食品微博政务移动集团公司八卦商店健康网店政府时尚佛山中信娱乐广东企业homedepotengineeringاماراتrepublicankuokgroupversicherungchannelcitadelxn--pgbs0dhxn--b4w605ferdstatebankwebsitexn--mgb9awbf亚马逊淡马锡alibabaxn--ngbc5azdxn--mgbbh1axn--45br5cyltoshibabuildworldcloudtradeguideplacespacedancemoviephoneprimesmilebiblestyleappleazurestoreskypegripexn--l1accdrivelottehorsehouseleasechasereisestadahondaomegaaetnaamicaninjanokiamediadeltavodkaedekaosakapizzaslingemailgmailtirolshelltmallfinallegaltotalhotelamfamforumrehabmusicciticricohcoachwatchboschearthfaithirishmiamiarchidubaiguccipraxiみんなストアセールcanonsalononionnikonepsonkoelngreensevencrownikanoradioaudioweiboglobopromogalloyahoociscorodeovideomangobingotokyovolvolottokyotophotosmartsportquesttrusthyattjetztadultcymrubaidutushuxn--kprw13dubankclickblackmerckgroupsharpcheapnowtvxn--h2brj9cקוםհայоргсрбмонкомбелмкдқазрусукрمصرقطرعربكومdadcfdmedwedredphdthdbidpidkrdmsdltdiceonewmeglemoerwecfageacbanbambaaaammakianraspacpaaxawtfbcgaegongingaigvigorgdogdhlmilrilonlaolloluoljllcalgalnflafltelsrlfrllplkimibmcamcombommomifmabbjcbscbwebcabnabtabmlbpubabcbbcnecincpncllcstcwtcpwcnyckfhbzhovhmoiskiobisbitcifyituipinvinwinxincbnbcnmanfangdnmenrenkpnmtnyunrunfununobiojioriohbogmofooboooooacoecoceongoproartistottnttbbtcateatlatvetpetbetnethktmitfitintjothotgotdotbotprueduicujnjyouinknhktdkappsapgapmapdnptopgopllpjmpzipvipripesqtrvdtvitvdevmovgovhivnrwlawsewnewbmwwownowhowdvrftrmtrsfrbarcartvscrseusawsupsubssbsadsddsldssasbmsmlsxxxboxfoxgmxtjxsextaxbuyflydiysoyjoyskypaydaygayxyzanzbizwebersenerpokerlameractortatarsolarລາວคอมไทยtourslocusnexuslexusgiftsbeatsboatspartspressglassswissकॉमनेटtiresgivescodeshomesgamestunesshoescardswalesloansvegastoolsdealsautosparisファッションworkssucksrocksxeroxforexfedexpartylillymoneystudyrugbytoraytoday中文网xn--unup4y天主教飞利浦新加坡enterprises我爱你嘉里大酒店christmasxn--fct429kholdingsxn--8y0a063axn--mgbx4cd0ablifestyleabogadoallstatenetbankكاثوليكxn--s9brj9cxn--gk3at1ebestbuycharityxn--55qx5dmicrosoftpropertybasketballhomegoodscorsicajewelrygallerygrocerysurgerycountrybrusselsverisignferreroxn--czr694bhdfcbankcommbanksoftbankپاكستانپاکستانnextdirectالسعوديهالعليانxn--h2brj9c8cxn--80adxhksshikshaxn--mgbai9azgqp6jcuisinellabarclayscatholicxn--kpry57dcompanyxn--xhq521bblackfridayxn--mgba3a3ejtsandvikxn--d1acj3bacademydownloadمليسياxn--j1amhxn--w4r85el8fhu5dnraipirangaathletaxn--fhbeixn--mgbqly7cvafrzuerichxn--c2br7gஇலங்கைcontractorsxn--io0a7igraphicsinsurancetemasekxn--xkc2al3hye2amotorcyclesphotographydirectoryplumbingxn--vhquvclothingtrainingcleaningwilliamhilllightingxn--mgba3a4f16ashoppingcateringeducationokinawapicturesventuresproductionsxn--9et52uwalmartഭാരതംsupportrealestatecapitalonexn--nqv7fs00emaauspostfloristdentistxn--qxamgodaddybradescobargainsmitsubishikerryhotelsxn--9dbq2axn--3pxu8kimmobilienxn--fjq720axn--mgbtx2bholidaymckinseymadridbusinessbuildershelsinkixn--4gbrimмоскваالسعودیةcoffeedegreelacaixapartnersalsaceofficeabbvievoyageorangegeorgeonlinechromemobilekindlegoogleoraclecircleschulesecureinsurexn--mgba7c0bbn0aestatexn--mgbc0a9azcgcruisehangoutxn--vuq861bxn--42c2d9arexrothfirestoneuniversityxn--nnx388alifeinsuranceextraspaceонлайнvermögensberatersoftwarexn--fiqs8sxn--mgbab2bdxn--w4rs40ltiendaभारतम्africatoyotaotsukasakuracameracreditcardnagoyaconsultingnetworkjunipertheatermonsterprogressivepioneerxn--55qw42gracingdatingvotingvikinglivinggivingxn--bck1b9a5dre4cbrotherweatherjoburgفلسطينlplfinancialxn--clchc0ea0b2g2a9gcdfutbolschoolsocialglobaldentalwoodsidechanelairtelmatteltravelrealtorwebcamstreamభారత్unicomalstomxn--nodexn--6frz82gmuseumfurniturexn--rvc1e0am3exn--mix891faccenturexn--11b4c3dismailineustardiscountquebeccomsecclinicservicesxn--y9a3aqxn--c1avgswatchchurchsearchالاردنmarketingcontacthealthmonashshoujisanofitaipeiamericanexpresssuzukiアマゾンクラウドポイントbhartiグーグルxn--mgberp4a5d4armemorialxn--1qqw23alondonmormoninstitutevisionbostonnortoncouponmaisonamazonvirginberlindesigndurbanolayannissananquanxihuanhitachikaufengardenreisenbayerntechnologydatsunxn--90a3aclatinocasinostudiophysioxn--ngbe9e0apharmacytattootaobaoaramcoexpertreportabbottdirectselectimamatfairwindspictettargetmarketintuittravelersinsurancecreditdupontryukyusuppliesxn--tckwebnpparibasschmidtmerckmsdyodobashirestaurantbridgestonecricketxn--fpcrj9c3dbostikbroadwayattorneylefrakemerckxn--fiq228c5hscareersfarmerswinnersflowersxn--wgbh1cguitarsxn--54b7fta0ccxn--p1acfmakeupgalluplandroverxn--kcrx77d1x4agoldpointbauhausxn--mgbayh7gpahiphopplaystationxn--mgba3a4fraxn--eckvdtc9dhyundaixn--gckr3f0fistanbulticketsmarketsflightschintaireviewsxn--3e0b707ewindowsxn--fiqz9sfinancialxn--fzys8d69uvgmابوظبيdiscoverreviewবাংলাxn--5su34j936bgsgmoscowobserverapartmentsдетиارامكوсайтeurovisionxn--i1b6b1a6a2exn--xkc2dl3a5ee0hتونسموقعبارتڀارتشبكةعمانبيتكعراقreadkredbondlandbandfundfoodprodgoldfordtubecafesafelifeggeeieeefreefagepagegugezonewinememenamegamesaleablebikenikelikecarecbreherefiresaveloveliveblueartedatesitevotecaseluxebofamodaltdaasdatiaayogasinavanashiaasiajavabbvatevavivadatazaraarpacasavisasncfprofmaifsurfgolfdvagsongbingpingwangkpmggoogblogpohlfailcooldellcalldeallidlsarlfilmteamroomfarmimdbarabclubhdfcicbchsbcgmbhrichtechfishdishcashminiernikddiaudiwikimobitaxicitikiwidesiqponskinloanakdnwienopenporncerntownimmolimoolloinfonicofidolegosaxozeroaerovivoautovotomotofastbestresthostpostnextlgbtchatseatgiftmeetdietreitmintrentgentspotscotguruitausohumenucyoubanklinkpinkdclktalksilkbookseekworkrsvpaarpjeepshopcoophelpcamppccwshowbeerstarruhrflirweirhaircarsparsjprshausplusnewstipstoysjobskidsfanspicsdocsxboxamexsexynavycitysonyarmyallybabyplaydeliverybuzzgbizlamborghiniphilipsලංකාಭಾರತfitnessexpresslanxesspfizercenterwalterlawyersoccercareerkosherbrokerlockerdealerdoctorauthorxn--mgbqly7c0a67fbcvermögensberatungjaguarxn--pssy2uxn--hxt814eflickrrepairrogersairbusxn--mgbai9a5eva00beventsyachtsxn--t60b56aভাৰতভারতभारतभारोतviajeshermeshughesxn--j1aefसंगठनvillasଭାରତclaimshotelsભારતzapposphotosjuegoscondostatamotorsgratistennisਭਾਰਤtkmaxxtjmaxxschaeffleryandexxn--80aswgrealtysafetybeautyluxuryxn--3ds443gsupplyfamilyxn--o3cw4hhockeysydneyxn--90aenissayalipayenergycomputeragencyxn--rovu88b電訊盈科xn--gecrj9cstatefarmaccountantaquarelleolayangroup香格里拉xn--p1ai组织机构xn--1ck2e1bxn--mgbt3dhdschwarzموريتانياabudhabinowruzkomatsufujitsuhospitalxn--80asehdbxn--mgbtf8flxn--j6w193gxn--yfro4i67oprudentialxn--flw351ecruisescoursesrecipesxn--e1a4cferrarixn--ses554gxn--wgbl6awatchesstaplessinglesxn--mgbcpq6gpa1axn--otu796dpropertiescreditunionxn--mgbah1a3hjkrdstockholmhisamitsuالسعوديةstcgroupdomainsoriginscouponsbloombergclubmedfroganslimitedxn--80aqecdr1aexposedinternationalequipmentbarclaycardxn--q7ce6axn--mgbi4ecexpprotectionassociatesconstructionxn--cck2b3bxn--45q11candroidfoundationישראלxn--mgbca7dzdocliniqueboutiqueengineerxn--qxa6asystemsfirmdalefashionauctionxn--nqv7finfinitirentalsreliancetradingweddingfishinghostinggentingbookingcookingxn--3hcrj9cgraingerxn--czrs0tdemocratsamsungyokohamaxn--h2breg3evexn--nyqy26alundbeckmelbournevacationssolutionsfrontierxn--vermgensberatung-pwbmanagementxn--cg4bkixn--mgb2ddeslincolnhamburgsandvikcoromantblockbusterairforcebarefootxn--4dbrk0ceinvestmentsfeedbackcommunityxn--ngbrxالبحرينdiamondsamsterdamhealthcareredumbrellaxn--mxtq1mxn--2scrj9cagakhanxn--mgbpl2fhкатоликcaravanசிங்கப்பூர்richardlimortgageamericanfamilyxn--fzc2c9e2cscholarshipssaarlandxn--imr513nvlaanderensamsclubgoodyearkitchenஇந்தியாweatherchannelallfinanzxn--kput3iالسعودیۃxn--90aisxn--efvy88hالجزائرxn--mgbaam7a8hexchangejpmorganxn--tiq49xqyjfidelitysecurityxn--mk1bu44cwanggouxn--fiq64bxn--6qq986b3xlxn--mgbbh1a71exn--80ao21amarshallsxn--5tzm5gtravelerspanasoniclatrobeyoutubeaccountantsxn--rhqv96gxn--cckwcxetdanalyticsxn--ygbi2ammxبازاربھارتسوريةorganicfreseniusسورياxn--9krt00axn--qcka1pmcxn--jlq480n2rgdeloittesciencefinancexn--jvr189mxn--30rr7yhomesensehotmailbaseballfootballleclercboehringerxn--q9jyb4cxn--mix082fاليمنهمراهpolitieسودانايرانایرانnetflixyamaxunxn--lgbbat1ad8jcollegestoragecapetowncolognekerrypropertiesxn--mgbgu82axn--ogbpf8flxn--czru2dwhoswhociprianilasallexn--g2xx48cforsalebanamexaudiblexn--vermgensberater-ctbxn--zfr164bericssonvanguardxn--45brj9cindustriestheatremarriottxn--3bst00mcomparexn--mgberp4a5d4a87gcapitaldigitalالمغربbarcelonashangrilaxn--d1alfcalvinkleinwwwcitysapporokawasakinagoyasendaikobekitakyushuyokohamackjp".charCodeAt(offset) === 42) wildcardEdge[node] = edge;
		offset = end;
	}
	let matchNode = -1;
	let matchStart = 0;
	let matchEnd = 0;
	/**
	* True if edge `edge`'s label equals `hostname[start, start + length)`.
	*/
	function labelEquals(edge, hostname, start, length) {
		if (edgeLength[edge] !== length) return false;
		const offset = edgeOffset[edge];
		for (let i = 0; i < length; i += 1) if ("orgmilcomschnetedugovdrrformsfeedbackofficialaccoorgmilschnetgovmagazinemediaunioncargopilotgroupcaarespressworksaerodromeworkinggroupair-traffic-controlaircraftaccident-preventioneducatormarketplaceambulanceinsurancecateringairportrepbodyenginesoftwaremodellingair-surveillanceconsultingchartertrainermaintenanceservicesdesignflightskydivingfreightassociationstudentgroundhandlingdgcafuelclubtaxicrewshowballooningexpresstraderbrokerauthoragentsairtrafficjournalistsafetyconsultantmicrolightaccident-investigationparachutingequipmentproductionfederationrecreationscientistnavigationengineertradingglidingleasingresearchpassenger-associationentertainmentparaglidinghangglidingaerobaticrotorcraftemergencycertificationgovernmentaeroclubexchangelogisticschampionshiphomebuiltcouncilconferencecontrolairlinecivilaviationjournalorgcomnetedugovcoorgcomnomnetobjofforgcomnetuwukiloappsframerorgmilcomnetedugovcoradioorgcomnetcommuneedogpbcoitgvorgedugov*spreviewfrontendrelayononstagingupid*mtls*privatelinktypedreamdeveloperbravemochawindsurfaivenmirenupsunwnextbegetngrokclerkwale2bwebcsbrunputerflutterflowspawnbaseshiptodaymagicpatternsnetlifyondigitaloceanrailwayhostedclaudehasurabotdashvercelgithubluyanigadgetreplitcloudflaretelebitedgecomputeevervaultexponyatnoopencrpplxzeaburwasmerframerzeropsrocketpreviewconvexmedusajsspritesonherculeseasypanelstreamlitsnowflakemesserliloginlinehackclubcodepennorthflankbase44corespeedleapcellngrok-freeclerkstagelovableon-fleek*us-west-3ap-south-2us-central-2us-central-1eu-central-1ap-south-1us-west-2us-east-2eu-north-1ap-north-1us-west-1us-east-1*rcloudintsegorgmilcomgobbetnetintedugovturmusicasenasamutualcoopip6uriurnin-addre164homeirisgovdixdaemoncloudnssthwien*inexexkunden4accogvormymyspreadshop4lima2ixortsinfofuturecmsfuturehosting12hpprivfuturemailinglima-cityfunkfeuer123webseitednshomemelmyspreadshopcloudletswasantqldvicactnswtascatholicwasaqldvictasidwasantozqldorgcomvicasnactnetedugovnswtasconfcomairflowlambda-urltransfer-webappairflowtransfer-webapptransfer-webapptransfer-webapp-fipstransfer-webappeu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1privatenotebookstudiolabelingnotebookstudionotebooknotebook-fipslabelingnotebookstudionotebook-fipsnotebookstudio-fipsnotebook-fipsnotebookstudionotebook-fipsnotebookstudioeu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2experimentsus-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1onrepostsagemakercopporgmilcompronetintedugovbiznameinfoshoprsorgmilcomnetedugovbrendlyresolvenzauscotvstoreorgcomnetedugovbizinfoidacaicoittvorgmilcomschnetedugovinfocloudezproxyacmymyspreadshopkuleuvenwebhostingtransurl123websitecloudnsinterhostsolutionsddns5476103298edgfacbmlonihkjutwvqpsryxzbarsycoororgcomedumyftpno-iporxcloud-ipfor-somemmafanfor-morewebhopselfipjozidyndnscloudnsdscloudfor-thefor-betteractivetrailcoeconorestooteorgcomeconeteduassurmoneyafricaarchitectesrestaurantloisirstourismavocatsinfoagrounivcoorgcomnetedugoviatvdeportesaludtksatorgmilcomwebgobnetinteducienciaboliviarevistacooperativaempresanombreindustriamusicapatriamedicinademocraciapoliticapuebloindigenaplurinacionalarteblogwikiinfoagrotransportenoticiasprofesionalacademiaeconomiaecologiamovimientotecnologianaturalsimplesitecepesebamapadfmgalampbacscpirngorotomtrjspaprrprrsesmscepesebamapadfmgalampbacscpirngorotomtrjspaprrprrsesms*biaamfmtcmptvfeirasampajampanatalbelemananiradiog12medindfndbmdtrdthepoaggfjdfdefinfenflegsegongengcngorgzlgslglogppgmillelqslcimcomnomadmjabimbbibbsbabcrectecsjcetcpscpvhudieticriapipsiecnbiorioecogeoteoodoproatoartfstmatvetdetbetnetcntnotfotgrueduajuespappreptmpemparqsrvadvdevgovntrturagrjorfarjusmusdesvixxyzcozfozslzbhzmaringasantamariacampinagrandegoianiasorocabafloripasaobernardocuritibaboavistarecifeaparecidasaogoncasalvadorcuiabamorenamacapalondrinacontagemsocialfortalmaceioleilaoosascoriobranconiteroi9guacutcheblogflogvlogwikitaxicoopmanauspalmascaxiasjoinvillebaruericampinassantoandreribeiraoriopretoweorgcomnetedugovv0windsurfshiptodaycloudsitecoaccoorgnetgovofmilcomgovmediatechzacoorgcomnetedugsjgovmydnspenfnlabnbmbgcbcqconcontnuyksknsmyspreadshopno-ipawdevboxbarsyonidatemfuinabusavinstanceseceuguukussryzespawncsxcloud-ipmyphotosfantasyleaguetwmailcleverappsscrappingccwucloudnsftpaccessgame-serverccgovobjectsrmalpgcust*svcalp1aeappenginermalpgmyspreadshop4lima2ixsquare7cloudscale123websitefirenet12hpflowgotdnslinkyard-cloudcloudnslima-citydnskingobjectstorageedaccogoorusorgcomnetinteduaéroportxn--aroport-byaassogouvcomilgobgovcloudnses-1eu-west-1us-east-1euvipit1eurarubait1s3lbwebsites3websiteru-spbru-mskelasticcsrunstnukukcaukusnl-ams-1fr-par-1fr-par-2functionsnodess3ddlwhmrdbfnck8sifrs3-websitecockpitscblmgdbdtwhkafkpubprivs3ddlwhmrdbk8sifrs3-websitecockpitscblmgdbdtwhkafks3ddlrdbk8sifrs3-websitecockpitscblmgdbdtwhkafkk8sscalebookpl-wawfr-parnl-amsbaremetalsmartlabelinginstancesdechk2kuleuvenlaravelvoorloperurownoxazapscwhstgrvaporonline-serverobservablehqelementorantagonistreclaimjoteluluencowaydiademjelasticmatlabmagentositetrendhostingaxarnetperspectajenv-arubajelejoteravendbemergenttrafficplexconvexkeliwebserveboltbegetcdnstaticson-rancherprimetelonstackitunison-servicesdnshomelinkyardbarsyjelecloudnscocomnetgovmycn-northwest-1cn-north-1s3s3-accesspoints3-websites3s3-accesspointrdsdualstacks3-deprecatedemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspoints3s3-accesspointrdsdualstackemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicn-northwest-1cn-north-1cn-northwest-1ebcomputeelbcn-north-1airflowcn-northwest-1cn-north-1oncn-northwest-1cn-north-1amazonawssagemakeramazonwebservicesdirectasgdsdhehahljlnmhbacscahqhshhihnlnynsnmofjbjzjxjtjhkcqtwgsjssxnxjxgxxzgz網絡网络公司orgmilcomnetedugovxn--55qx5dcanva-appsxn--io0a7iquickconnectcanvasitekhsjxn--od0algcanva-codemyqnapcloudsrvrlessclustersrealtimestorageleadpagescarrdcrdorgmilcomnomnetedugovhidnssupabaserdpareplmypiumsoxmitotaplpagesfirewalledreplitowodevwebview-assetsvfswebview-assetss3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9eu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1s3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackanalytics-gatewayemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackemrappui-prods3-websiteemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspointdualstacks3-deprecateds3-websites3-object-lambdaexecute-apis3s3-accesspoints3-websites3-accesspoint-fipss3-fipss3s3-accesspointdualstackemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstackemrappui-prods3-websites3-accesspoint-fipss3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apis3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9vfss3s3-accesspointdualstackemrappui-prods3-websiteaws-cloud9emrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9eu-west-3ap-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1us-northeast-1ap-southeast-1me-south-1af-south-1ap-south-1ap-southeast-7us-west-2eu-west-2ap-east-2us-east-2ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ap-southeast-6ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1mrapaccesspoints3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3s3-accesspointdualstacks3-deprecatedanalytics-gatewayemrappui-prods3-websites3-accesspoint-fipsaws-cloud9s3-fipsemrstudio-prods3-object-lambdaemrnotebooks-prodexecute-apicloud9s3eu-west-3ap-south-2eu-south-2computes3-ap-northeast-2elbrdss3-ap-east-1s3-sa-east-1s3-us-gov-west-1s3-eu-central-1s3-ca-central-1eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3s3-website-us-west-2s3-website-eu-west-1s3-external-1eu-central-1me-central-1ca-central-1il-central-1s3-us-west-1s3-eu-west-1s3-website-sa-east-1s3-website-ap-southeast-2ap-northeast-1ap-southeast-1s3-us-west-2s3-eu-west-2me-south-1af-south-1eu-south-1ap-south-1us-west-2eu-west-2us-east-2s3-website-ap-southeast-1s3-1s3-globals3-ap-northeast-3eu-north-1airflowap-southeast-2s3-us-gov-east-1s3-fips-us-gov-east-1s3-me-south-1s3-ap-south-1ap-northeast-2s3-website-us-west-1ap-southeast-5s3-eu-north-1s3-ap-southeast-1s3-website-us-gov-west-1compute-1s3-eu-west-3us-gov-west-1s3-website-ap-northeast-1us-gov-east-1s3-fips-us-gov-west-1s3-website-us-east-1s3-ap-southeast-2ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1s3-us-east-2s3-ap-northeast-1authauthauth-fipsauth-fipseu-west-3ap-south-2eu-south-2eu-central-2ap-southeast-3ap-southeast-4ap-northeast-3eu-central-1mx-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1ca-west-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1rframeservicesbuilderstg-builderdev-builder*ociocpocsazuregcpawsdemoinstanceeu-west-3eu-south-2ap-southeast-3ap-northeast-3eu-central-1me-central-1ca-central-1il-central-1ap-northeast-1ap-southeast-1me-south-1af-south-1eu-south-1ap-south-1ap-southeast-7us-west-2eu-west-2us-east-2eu-north-1ap-southeast-2ap-northeast-2ap-southeast-5us-gov-west-1us-gov-east-1us-west-1eu-west-1us-east-1ap-east-1sa-east-1previeweu-4us-4us-1eu-1us-2eu-2us-3eu-3appscomputepaasrag-cloudrag-cloud-chjcloudjcloud-ver-jpcdemonodebalancermembersipeuxvsoncillaocelotonzayalilynxsphinxfentigercustomercaracalo365cloudstaticxendevapp001testcode-builder-stgplatformmediasiteprojedrydpagesjsx0desazacncoitrueu4uhkukgrbrushatenadiarymyspreadshopfrom-flfrom-wvwebspace-hosttheworkpchatenablogcursorusercontentservesarcasmapplinzisakuratanwixsiteappchizigiizeis-into-carsdnsiskinkyadobeaemcloudis-a-therapistpgfogmyvncdojinis-an-actress1kappfldrvkozowqa2jpnmexprgmrfirewall-gatewaydynnscafjsfbsbxooguyfrom-gawoltlab-demois-a-anarchistwiardwebteaches-yogadattowebtb-hostinglive-websiteservegamegotpantheonfrom-nhsubsc-payfrom-ohvipsinaappfrom-cadyndns-officehomelinuxfrom-mahercules-appservebbsstreakusercontentfrom-okfrom-wyfastly-terrariumis-a-llamaqualyhqportalserveexchangeon-vaporvivenushopciscofreakgrayjayleaguesmetaaiusercontentfrom-iais-a-libertariansaves-the-whalestaveusercontentyolasiteoperaunitepoint2thisis-a-catererclaudeusercontentlinodeusercontentfrom-vagithubusercontentsells-for-lesshosteurcanva-appsplaystation-cloudddnsfreefrom-pafrom-prfrom-waddnskingoutsystemscloudhotelwithflightmydattois-a-nascarfanmydbserverminiserverdamnserverservehumouris-a-playerfrom-nvfrom-nmemergentagentgentappsamplifyappfrom-kyis-an-accountantnfshostserveircfrom-akpythonanywherestackhero-networkpostman-echolikescandydyndns-mailobservableusercontentserveftpfreeboxosfrom-utcdn77-storageamazonawsneat-urldyndns-serverlinodeis-a-teacherfrom-vtgleezemythic-beastsus1-pleniteu1-plenitla1-plenitpaywhirlservecounterstrikejdevcloudhealth-carereformis-into-animegoogleapisis-a-painterafricaisa-hockeynutatmetais-an-actora2hostedis-a-democratdatadetectest-le-patrondigitaloceanspacesis-a-designeris-a-hunterlinodeobjectstemp-dnsissmarterthanyoufrom-arsimplesiteevennodetownnews-stagingis-a-liberalgooglecodejelasticservemp3qualyhqpartnerdyndns-free1cooldnsest-a-la-masiondrayddnsdynuddnsfrom-orfrom-miis-a-bloggerfrom-himydobisscanvacodeis-an-engineerest-a-la-maisonupsunappdevinappswafflecellmyasustorwpenginepoweredfrom-ctservep2psame-appmyshopblocksthingdustdatalikes-piediscordsezis-with-thebandlpusercontentis-leetshopitsite3utilitiesis-a-personaltrainersinaappladeskis-a-cheflogoipselfipbase44-sandboxnospamproxyalibabacloudcsmesswithdnsauthgearappsiamallamawithgooglelutrausercontentmochausercontentframercanvasmytabitdyndns-homew-credentialless-staticblitzcpserverdiscordsaysis-a-nurseappspotatlassian-isolated-3premotewdfrom-mtwixstudiocode0emm180rmyactivedirectoryawsappsmytuleapdnsabrpolyspaceqbuserrenderbuiltwithdarkboutirgotdnsabrdnsdopaascanva-hosted-embedawsglobalacceleratorhomesecuritypcmyiphostditchyouripclever-clouddyndns-ipon-aptibleis-a-musicianhosted-by-filessecuritytacticsappspaceusercontenthomeunixstrapiappsame-previewcf-ipfsmycloudnaselasticbeanstalkis-certifieddontexistkasserverik-serverdrive-platformatlassian-3pfirebaseappherokuappawsapprunnerbarsycenteris-a-cubicle-slaveservehttpmyshopifyis-a-guruquicksytessiiitesorsitesmagicpatternsappis-a-cpameteorappfrom-wiis-a-rockstarbumbleshrimpdattolocaldatabricksappsreadthedocs-hostedfrom-rifamilydsdyndns-picsplesknsbplaceddnsaliasdynaliasdyndns-remotedoomdnsip-ddnsblogdnsis-a-doctorroutingthecloudamazoncognitobarsyonlinedsmynasddnsgurucloudflare-ipfsdeus-canvasfrom-idsmushcdnpagespeedmobilizerdyndns-at-homeunusualpersonhosted-by-previderis-a-republicandyn-o-saurstreamlitappworkisboringonthewificprapidqualifioappis-uberleetis-slickgetmyipwpdevcloudtypeformdyndns-at-workgentlentapismynascloudw-corp-staticblitzfrom-ingeekgalaxyservebeerfrom-mdonrenderspace-to-rentaivencloudappspacehostedwafaicloudcodespotblogspotatlassian-3p-us-gov-modfrom-ndfrom-msis-a-techieis-a-studentcustomer-ociis-a-photographerdurumisfrom-ksmassivegriddyndns-wikiis-an-entertaineris-a-hard-workermysecuritycamerafrom-mnrackmazedyndns-blogis-a-bulls-fanwritesthisblogfreemyipsimple-urlfrom-sdreservdauthgear-stagingest-mon-blogueuris-into-gamesrice-labsxtooldevicesakurawebis-an-anarchistoraclecloudappsdyndns-worksells-for-urhcloudfrom-dcfastvps-serverwpmucdnis-a-geekscrysecfrom-txis-into-cartoonsmodelscapetrycloudflarelocaltonetstreak-linkbalena-devicesfrom-njforgeblocksfreebox-oswebadorsitefrom-ncdoesntexisthobby-sitestreaklinkshomesecuritymacownprovidertuleap-partnersdattorelaywphostedmailservequakeis-a-socialistservehalflifepivohostingdynuhostingquipelementsw-staticblitzdyndns-webfrom-deproject-studyaliases121is-not-certifiedhercules-devis-a-financialadvisorservepicsis-a-greenloseyouripfrom-ilwithyoutubemwcloudnonprodwiredbladehostingdnsdojofrom-tnpixolinomyqnapcloudis-an-artisthostedpiis-a-landscaperauiusercontentoaiusercontenton-forgeis-a-conservativedreamhostersnet-freaksapps-1and1is-goneencoreapifastly-edgefrom-nesalesforcefrom-scdeployagentoraclegovcloudappsfrom-alis-a-lawyercechirevultrobjectsstufftoreadisa-geekddnsgeeklovableprojecttry-snowplowfrom-moblogsyteis-a-bookkeepernogmyforumravendbmyboxdeelementoredsaacficogoorinforgcomgobnatneteduidstoreorgcomnetintedudevnomepublorgcomneteduathgovtestscalculatorspaynowinfoquizzesresearchedcloudnsfunnelsassessmentsjscaleforcetmacltdorgmilcompronetgovbizpresseklogesrsccloudcustomfltusrcloude4corealmgovmunicontentproxy9metacentrumdyndyndyndnsdynpagespages-researchitionoccustomercomymyspreadshopipv64diskussionsbereich4limacomrub2ixfirewall-gatewayddnssspdnsbarsykeymachinesquare7myhome-serverspeedpartnercommunity-proschuldockxenonconnectgünstigliefernbwcloud-os-instancedyndnssecmy-routerxn--gnstigliefern-wobin-butterl-o-g-i-nisteingeekin-dslin-berlinin-brbfuettertdasnetzleitungsenin-vpnlcube-serverdyn-ip24logoipdyn-berlinruhr-uni-bochum12hpgoipsrvdnsfruskygit-repossvn-reposinternet-dnsgünstigbestellenhome-webserverxn--gnstigbestellen-zvbbplacedheimdnscosidnswebspaceconfiglima-citydyndns1istmeinvirtualuserschulplattformmy-gatewayddnsseclebtimnetztest-iservmein-iservvirtual-userhome64iservschuletaifun-dnstraeumtgeradeschulserverdynamisches-dns123webseitednshomehs-heilbronndnsupdaterbssgraphicdwadpdwdaepeweaawapaafpfwfabwbpbacwcpcciwebuserapiobjectsidsiskospockkimodorikerbonesteamsparisjanewaypicardglobaltarpitreedpikekiraworfsulukirkarchertuckerhackercanarywesleystagingprereleaset3r2lpbravepanelngrokiservstglclcrmerpflypagesbarsyvivenushoplocalcertlocalplayerbearbloggatewaydeno-stagingis-not-ais-a-goodbotdashvercelmocha-sandboxplatter-appreplitgithubpreviewworkersinbrowserevervaultis-ahrsndenoxmitmodxmyaddrstorageapipayloadgrebedocruncontainersstgstagelclstageloginlineis-a-fullstackcodepenleapcellngrok-freeis-coolstoragewebharemediatechlibp2pdiscourseimaginecomyspreadshopstoreregbiz123hjemmesidefirmcoorgcomnetedugovsldorgmilcomwebgobartnetedugovtmorgpolcomsocartnetedugovassoagrondiscoodontk12medcuegyecpaabgengorgmilgalsaltulcomadmesmgobpubdocmonfindgnriouioproartlatvetnetfotedulojgovntrturibrbarxxxofficialbasechefprofmktgpsictechinfoarqtcontdentrrpppsiqgit-pagesritmedfieorgcomlibprieduaipgovriikmeactvsportorgmilcomscieunnetedugovnameinfopintouchtawktotawkmyspreadshoporgcomnomgobedu123miwebcomputeorgcomnetedugovbiznameinfocognito-idpeusc-de-east-1onjelasticnxaspdnsbarsydirectwpdeuxfleurstransurldogadoprvwcloudnsamazonwebservicesdnshomeuserpartycokoobinmkmfidymyspreadshopalandkapsiikixn--hkkinen-5wacloudplatformhäkkinen123kotisivuidacorgmilcompronetedugovbiznameinforadioorgcomneteduuserexperts-comptablestmmyspreadshopgretaprdcomnomynhccifbxoshuissier-justicenotairesaeroportfreeboxoson-webavocatassoportgouvkdnschirurgiens-dentistes-en-franceavouesfbx-os123sitewebveterinairechirurgiens-dentistespharmacienchambagrimedecinfreebox-osdediboxgoupilemszicpyicpvicppleysheezypagesedugovcnpyorgcomcybllcpvtnetedugovtnxonlineschooldaemond6atcopanelorgnetplybotdashstackitkaasorgmilcomnetedugovbizmodltdorgcomedugovcoorgcomneteduappwriteacorgcomnetedugovcloudtranslateusercontentorgcomnetedumobiassoorgcomnetedugovbarsysimplesitediscourseindorgmilcomgobneteduorgcomwebnetedugovguaminfonxhra教育敎育網絡网絡组織組織网络網络组织組织公司政府個人个人箇人ltdorgcomincneteduidvgovxn--uc0ay4axn--55qx5dxn--mk0axixn--io0a7ixn--uc0atvxn--zf0avxxn--lcvr32dxn--od0algxn--wcvs22dxn--gmqw5axn--od0aq3bxn--mxtq1mxn--ciqpnxn--tn0agxn--gmq050iorgmilcomgobneteduiservwp2tempurlmircloudfreesitewpmudevmyfastgadgetcloudaccessjelehalfboltfastvpsemergenteasypanelopencraftizcombrendlynamefromrtpersoadultmedorgpolrelcomproartnetedufirminfoassoshopcoopgouvtmcomediahotelforumvideosportorgsexagrargameslakaseroticaerotikatozsdereklamcasino2000filmsuliinfoboltshopprivnewsszexcityutazasjogaszkonyveloingatlaneacaicogoormyᬩᬮᬶmilwebschnetkopbizzonedesaponpesxn--9tfkymyspreadshopgovmytabittabitorderravpageaccok12idforgnetgovmuniltdplcaccotttvorgcomnetmeca6g5gpgamubacaicniocoukuptverdruscsdelhiindorgmilcomwebnicfingenpronetintedugovresbizbiharbarsyinternetbusinessschooltravelsupabasealumnigujaratfirminfoaeropostbankcoopindevscloudnsno-ipbarsybarrell-of-knowledgebarrel-of-knowledgensupdategroks-thisdnsupdatefor-ourknowsitalldvrcammittwalddynamic-dnsv-infowebhopselfipdyndnshere-for-moreilovecollegemayfirstforumzcloudnsmittwaldservertypo3servergroks-theeusekd1cdndyndnsidrawsainaueuapjpusstagemocksysdevicesclientcustreservdcustdevdisrecprodtestingcobeebyteutwenteboxfusebravepstmndedynngrokorgmilcomnomnetedugovqcxqzzbarsythingdustmo-siemensrb-hostingfh-muenstergitbookbluebitecloudbeesusercontentnodeartkiloappsforgerockdarklangresinstagingapigeebubbleb-datascryptedhypernodedappnodepantheonsitegitlabgithubkeeneticvirtualservercleverappshostyhostingon-rioedugitticketstelebitwixstudioon-k3sicp0icp12038jeleqotolairbubbleappsmyaddrstolosmyrdbxwebflowdrive-platformbeagleboardhasura-applolipopdefinimavaporcloudmusicianwebflowtestazurecontainerresindevicereadthedocsloginlineeditorxmoonscalesandcatsbasicserverwebthingsbrowsersafetymarkbeebyteappbitbucketidaccovistablogorgschnetgovxn--mgba3a4f16axn--mgba3a4fraarvanedgeايرانایرانjclaspeziapdudcefegelemeperetevebacanatavaparasabgagfgogrgpgalclblimfmrmcbmbvbfclcmcvcrcpcchlimifibicivipirisimncnbnanenrnpntnnolomobocoaogorosopotoptvtatctbtmtltotpusulunutpspapaqsvpvvvtvavvrtrsrprgrfrcrbrarorkrvstsssbscsmsispzczbzbozen-suedtirolmyspreadshopxn--bulsan-sdtirol-nsbxn--valledaoste-ebbtrentinoaltoadigetrentin-sued-tirolxn--forlcesena-c8axn--forl-cesena-fcbxn--bozen-sdtirol-2obtriestetrentinsuedtiroltrentino-s-tirollecceudineaostesienaparmaluccapaviagenoapaduaaostamonzaabruzzoternirietiturinmilanbozenlaziofermoleccocuneonuoropratola-speziavdataaligfvgpugmolcalcamlomumbsicpmnvenvaoedugovabrsarmaremrbastoslazibxosfirenzetrentinosüdtirolval-d-aostavalle-aostamessinacremonaravennatoscanatrentin-suedtirolbolognacalabriaurbinopesarofriuli-v-giuliaogliastraxn--valle-aoste-ebblaquilaandriatranibarlettasyncloudxn--valle-d-aoste-ehbaostavalleyvalled-aostatrentino-alto-adigevallee-d-aostexn--balsan-sdtirol-nsbpistoiasicilialucaniacataniaiserniaperugiabresciaveneziagorizialiguriaimperiabulsan-suedtirolbalsan-suedtirolbarlettatraniandriaxn--trentino-sdtirol-szbforlì-cesenatuscanyvallée-d-aostemantovavallée-aostecasertapiemontevalleaostaval-daostafriulivgiuliatrevisoforli-cesenavalléedaosteferrarapescaravald-aostatrentino-altoadigefriuli-vegiuliavallee-aostecarboniaiglesiastarantomediocampidanovalleedaostetrentinosud-tirolcampobassotrentinsüd-tiroltrentinosüd-tirolmonzabrianzatrentino-südtirolxn--trentino-sd-tirol-c3bpotenzacosenzavicenzaemiliaromagnavenicefrosinonemarchepordenonetrentinosued-tirolvaresemolisevalléeaostefriuli-veneziagiuliabasilicatalatinaanconasavonaveronamodenabiellabolzano-altoadigepugliafoggiaumbriatrentino-stirolgenovapadovamateranovararagusapiacenzatrentinostirolvalleeaostetempio-olbiasudsardegnatrentinsudtirolmassa-carrarafriuliveneziagiuliatrentinosuedtirolandria-barletta-tranitrapanixn--cesenaforl-i8amaceratacaltanissettaascoli-picenobrindisicarraramassacagliaririmininapolivibo-valentiachietibulsan-sudtirolbalsan-sudtiroltrentino-a-adigebulsanbalsaniglesiascarboniamilanotorinoteramodell-ogliastraarezzotrentinoalto-adigerovigotrentovenetoiglesias-carboniatrentino-sud-tirolaltoadigereggio-emiliareggio-calabriasardegnatranibarlettaandriapiedmontxn--sdtirol-n2amedio-campidanotrentino-süd-tirolfriuli-vgiuliafriuli-ve-giuliaromeennaromapisa32-b16-b64-blodiastibarineencomonaplesforlicesenailiadboxosalessandriasicilytrani-barletta-andriaxn--trentin-sdtirol-7vbpesarourbinotrentinsued-tirolcesena-forliforlìcesenaemilia-romagnamonzaebrianzaxn--trentinsdtirol-nsbtrentinos-tiroltrentinsüdtirolvalledaostaolbia-tempiocampidanomediovibovalentiasassarivalle-daostalombardysud-sardegnafriulivegiuliareggioemiliamonzaedellabrianzaalto-adigevercellitrentin-sudtiroltraniandriabarlettatrentino-sudtirolascolipicenobozen-südtirolfriulive-giuliaflorencexn--cesena-forl-mcbcarbonia-iglesiasaosta-valleycarrara-massadellogliastratrentinoa-adigexn--valleaoste-e7apesaro-urbinoxn--trentinosdtirol-7vbxn--trentin-sd-tirol-rzbxn--trentinsd-tirol-6vbtrani-andria-barlettatrentin-süd-tirolxn--trentinosd-tirol-rzbgrossetomonza-e-della-brianzasüdtirolreggiocalabriatrentinoaadigetrentin-südtirolverbano-cusio-ossolafriuliv-giuliaverbaniacampaniatrentino-aadigefriulivenezia-giuliasardiniaandriabarlettatranibarletta-trani-andriacatanzarooristanourbino-pesarocesena-forlìvalle-d-aostacampidano-medio123homepagesiracusatempioolbiasuedtirollombardiaavellinocesenaforlìtrentinofriuli-venezia-giuliabozen-sudtirolandria-trani-barlettabulsan-südtirolbalsan-südtirolmonza-brianzabolzanotrentino-sued-tirolbellunosalernolivornocrotonesondriodnshometrentinsud-tirolmassacarraratrentin-sud-tiroltrentino-suedtirolviterbobergamocesenaforliolbiatempiopalermobeneventoagrigentoofcoorgnetfmaitvphdengorgmilcomschnetedugovperagrikanieasukehandachitatokaiaisaikonanoharuamaobuhigashiuraowariasahiinuyamatobishimaiwakurashitarainazawatoyonegamagorimihamatoyotataharakariyayatomioguchikomakimiyoshinishiotokonamekiyosuchiryutoyohashiokazakiisshikikasugaikotakiratoeianjotogofusosetohazutsushimashinshirotakahamanisshinshikatsuhekinantoyokawaichinomiyatoyoakeodateogataakitaikawakyowahonjoogayurihonjonoshirokamiokakatagamimitanegojomeyokotekosakadaisenkazunonikahohonjyomoriyoshimisatohappoukamikoanihachirogatahigashinarusesembokufujisatokitaakitaitayanagiowanitakkomutsutsurutahirosakigonoheoirasetowadamisawanohejiaomorishingohiranairokunohehashikamitsugarushichinohehachinohenakadomarisannohekuroishisakaeisumiasahiotakiinzaiabikomatsudoyachiyomutsuzawakujukuriomigawakashiwatoganemihamanaritasakuranagaramobarahanamigawachoshishiroichoseikozakishisuikatorimidorichonankyonanfuttsuonjukufunabashinagareyamanodasosatakochuotohnoshourayasukimitsuyokaichibayotsukaidosodegauratateyamakamagayayokoshibahikariyachimatakatsuuratomisatokisarazukamogawaichikawanarashinoichinomiyashimofusaminamibososhirakoichiharaoamishirasatoikatahonaiainansaijoseiyoiyoozuuwajimaniihamanamikatamasakiuchikokihokutobetoonshikokuchuomatsuyamaimabarikamijimakumakogenyawatahamamatsunosabaeikedaobamasakaifukuiohionotsurugamihamawakasaminamiechizeneiheijikatsuyamatakahamaechizensoedaukihaomutaokawanishiogoribuzenonojosueumiokiotochikugosasagurisaigawamizumakishinyoshitomikurumekurateyamadakasuganakamamiyamanogatatakatahakataiizukakawaratagawakasuyaashiyainatsukimunakataminamitsuikishonaikurogifukuchikeisenhigashimiyakoshinguyukuhashiokagakiyamekogaongausuikahotohochuotoyotsumiyawakadazaifuhisayamatachiaraiyanagawanakagawahirokawachikujochikushinochikuhochikuzennamieotamaokumashowateneiiwakikoorinangoononishigoshimogoomotegomishimafukushimaasakawakagamiishishirakawaiitatefutabahiratayugawahanawakitakatakawamatakunimiyabukibandaihigashihironoyamatomiharuyamatsuriaizubangedatesomaaizuwakamatsuyanaizuaizumisatonishiaizuizumizakikitashiobarataishinkaneyamakoriyamainawashirotanagurafurudonosamegawasukagawaishikawatamakawaikedaogakitaruiginanenahashimahichisonakatsugawaibigawashirakawamizunamiminokamomitakekawauesekigaharatomikasakahogikitagatayamagatatajimianpachimotosuyaotsukakamigaharahidakanisekitokigujominogodoyorogifukasamatsutakayamawanouchihigashishirakawakasaharashimonitatsumagoichiyodakannakanrashowameiwakiryuotaoratomiokafujiokaitakuranaganoharahigashiagatsumatakasakishibukawaminakamikatashinatsukiyonokawabanumataannakaoizumimidorishintoisesakiuenoyoshiokakusatsutakayamanakanojonanmokutamamuratatebayashimaebashiotakekaitadaiwahongofuchukuietajimashobaramiharahatsukaichihigashihiroshimamiyoshikumanokurenakasakaseraseranishiasaminamifukuyamashinichionomichiosakikamijimajinsekikogentakeharaotobenanaeikedatohmaozoraobiraabirakyowaeniwataikibibaisharirebunerimohiroooketootarupippunishiokoppechitosefurubirahakodateshiranukakitahiroshimakushiroobihironanporoiwamizawaniikappukunneppufukushimanakasatsunaitoyourakuromatsunaiakabirakamisunagawashibechaurakawakamifuranonakatombetsuasahikawashimokawakayabeokoppebiratoriabashirisaromaatsumanumatahidakabifukamukawamikasahorokanaitoyotomisarufutsuhigashikawaishikarikitamiyoichiesashiiwanaitomariminamifuranoakkeshifuranotoyakoyakumootoineppushikaoishiraoinemuronayorohaboroashorobihororishirifujiutashinaihokutotakasuebetsuurausuassabukikonaishimamakinaiedatetoyabieinikiesanuryuoumuteshikagarikubetsuashibetsukimobetsuaibetsutobetsusobetsuembetsushimizuchippubetsurishirihokuryuhoronobeshintokutsubetsushibetsuhonbetsumombetsutsukigatakuriyamakoshimizushiriuchikutchanmurorannoboribetsukamishihorowassamushinshinotsukembuchiwakkanaikamoenaikiyosatotakinoueshikabesunagawafukagawanakagawatakikawakamikawahigashikagurahamatonbetsumatsumaemoseushirankoshishakotanimakanemashikeotofuketomakomaisandatambaitamiawajikasaiasagoshisoonoakoyashirotoyookaminamiawajiinagawafukusakitakasagokamigorikasugaharimayokawaashiyahimejiakashitaishiaogakisannantakinosumototakarazukanishinomiyashingugoshikinishiwakiyokatakaaioimikisayoyabukawanishiamagasakisasayamashinonsenkakogawaichikawakamikawatatsunotsukubaiwamaogawaasahisakaitokaioaraiitakobandodaigosuifuinaamikasumigaurakashimaomitamayachiyoshimodatetomobetoridehitachinakainashikisakuragawakasamayawaramoriyahitachiomiyanamegatayamagatahitachikamisuushikutakahagiibarakitonekoganakasowayukimihojosomitoryugasakishimotsumafujishirotsuchiurachikuseihitachiotashirosatotamatsukuriuchiharashikahakuinanaotsubatawajimakahokukawakitatsurugikaganominotosuzuuchinadakomatsuanamizunakanotohakusannonoichikanazawaiwateshiwafudaikawaimoriokaofunatohanamakikuzumakikitakamininohekunoheyamadayahabasumitaichinosekitanohatahiraizumirikuzentakatajobojiotsuchihironomiyakoiwaizumikarumaiichinohenodakujitonooshushizukuishifujisawamizusawakamaishikanegasakimannoutazukotohiraayagawazentsujihigashikagawauchinomikanonjisanukimarugamemitoyotakamatsutadotsunaoshimatonoshoakuneamamiizumihiokiyusuikinkoisasookouyamanakatanekagoshimakanoyaisenkawanabeminamitanemakurazakitarumizunishinoomotematsumotosatsumasendaioimatsudaayaseebinamiurazushinakaiodawaraiseharasagamiharahakoneaikawakaiseiatsugitsukuihadanoyamatoyamakitazamaoisochigasakininomiyayokosukakamakuraminamiashigarafujisawasamukawakiyokawahiratsukayugawaraokawaumajikochitsunootoyoakiinonishitosayasudahidakamiharasakawaniyodogawahigashitsunokagamigeiseisusakiotsukinaharisukumomurototosakamiochitoyotosashimizumotoyamanankokunakamurakitagawayusuharaogunichoyoukiasoutoozugyokutoamakusamifunetakamoriyamagaminamataminamiogunikikuchisumotoyamatonagasumashikiaraokumamotokamiamakusanishiharayatsushiroayabeseikasakyoideineujinakagyokameokakyotangokyotanabekyotambaminamiyamashiroyamashinatanabeyawatawazukaminaminantanmiyazuhigashiyamafukuchiyamakitamukokamojoyokizumaizuruujitawaraoyamazakinagaokakyokumiyamakawagoeinabeshimameiwaasahitaikiudonoisetsukisosakikuwanamihamamiyamasuzukatamakimisuginabarikumanokomonominamiisewataraitobakiwatakikihotadomatsusakayokkaichikameyamaureshinoishinomakishichikashukuohirataiwaosakizaohigashimatsushimashikamaiwanumashibataogawaraonagawakawasakiseminemarumoriminamisanrikukakudamuratawakuyatomiyanatoriwataritagajomisatotomekamirifushiroishimatsushimayamamotoshiogamafurukawahyugaebinotsunosaitoayakushimanobeokakitauramiyazakitakazakigokaseshiibamimatashintomikunitomikitakatakobayashikawaminamitakaharukijotakanabemiyakonojonishimeranichinankitagawakadogawamorotsukakisofukushimaminamimakisakaeobuseikedaogawamiasaokayaasahiotakiotarichinoinaomichikumakomaganechikuhokukaruizawayasuokaooshikaikusakaminamiaikitogakushimatsukawakawakamitateshinatakamorikitaaikishiojirimiyadahakubaiizunaiijimaiiyamamiyotasuzakayasakatoguraookuwanagawaminowahirayayamagataminamiminowafujimiomachisakakitakaginaganonakanosakuhokomoronagisoshinanomachiwadauedaiidaharasuwatomiachiaokianankisosakunozawaonsenagematsutakayamashimosuwamatsumotoyamanouchinakagawamochizukiazuminotatsunoobamaomuraseihiunzenosetofutsuikichijiwanagasakiisahayahasamisaikaikawatanasasebohiradokuchinotsugototogitsutsushimashimabarashinkamigotomatsuurayamazoekashibaikomakawaitenrioyodosangokoryoudaojiikarugayamatokoriyamatenkawakatsuragikurotakikawakamimiyakemitsuetakatorikamikitayamayamatotakadahegurishinjokanmakisakuraitawaramotogoseoudanarasoniandokawanishishimoichihigashiyoshinokashiharashimokitayamanosegawayoshinomintsivorytopazsakuragehirnsumomoaseinetopalmail-boxmokurenyoitamuikaojiyagosensanjoaganomyokoseiroagaomishibataniigatanagaokamurakamiuonumayuzawakariwatagamitainaitsunanminamiuonumatochioyahikojoetsuseiroukamosadoizumozakitokamachiitoigawasekikawakashiwazakitsubamemitsukekokonoesaikiusukibeppuusahimeshimakunisakihasamataketatsukumihitaoitahijikusuyufukujukamitsuebungoonobungotakadaibaraniimibizentsuyamaokayamakasaokahayashimayakagemaniwaakaiwamisakishinjotamanotakahashikibichuowakesojanagishookumenannishiawakurakurashikiasakuchisetouchikagaminosatoshotomigusukunakagusukuyaeseizenaurumaiheyaaguniogiminanjokinminamidaitokitanakagusukuyonaguniokinawaishigakikunigamiurasoekadenataramahiraraginozataketomishimojizamamitonakiitomanhigashimotobuyonabarugushikamionnanahanagohaebarukumejimakitadaitonakijinnishiharayomitanginowantokashikiishikawaikedasuitaminohizuminishisakaikananabenodaitoosakasayamayaokishiwadatadaokakaizukatondabayashichihayaakasakakumatorikadomasayamahigashiosakashijonawatehirakatataishimisakitajirihannansennankatanotoyonominatosettsuhigashiyodogawaibarakinosekitachuohigashisumiyoshifujiiderakashiwaraizumiotsutoyonakamatsubaramoriguchiizumisanoshimamototakatsukineyagawahabikinotakaishikawachinaganoyoshinogarikamiminearitaouchiimarihizenogikashimaariakekiyamafukudomikitagatakitahataomachigenkaikanzakinishiaritakyuragisagataratosutakushiroishikaratsuhamatamakouhokukawagoeyoshidasatteogoseirumaasakaurawaogawaniizaomiyayoriiotakishikihonjooganohannohanyuinasaitamaokegawaarakawayoshikawayokozehasudasayamahidakafukayachichibuiwatsukiryokamiyoshimikamiizumifujimiwarabiranzanmiyoshiminanoyashiosakadosugitomisatohigashichichibutodasokakukiyonokazoshiraokakasukabekounosukawajimatsurugashimamiyashirokitamotohatoyamamoroyamahatogayakumagayakawaguchinagatorokamisatomatsubushinamegawatokigawakamikawafujiminohigashimatsuyamakoshigayatokorozawas3isk01isk02ryuohkoseikonanaishorittotakashimamaibarahikonetorahimenishiazaikokagamokotoyasuotsukusatsunagahamamoriyamatoyosatotakatsukinotogawaomihachimanhigashiomiakagiunnanizumogotsuamayatsukakakinokimatsuehamadamasudahikawahikimiokuizumoyasugiyakumomisatotamayuohdahigashiizumookinoshimanishinoshimatsuwanoshimaneshimadafujiedayoshidashimodagotembaiwataatamikosaiyaizuitoizumishimahaibaramakinoharaomaezakikawanehonkannamisusonohigashiizufukuroinumazukawazufujiaraishizuokahamamatsushimizuizunokunimatsuzakimorimachiminamiizunishiizukikugawakakegawafujikawafujinomiyaujiietsugaoyamayaitaohiranikkoashikagakuroisokanumasakurashioyakarasuyamamotegiichikaikaminokawatochigihagamokanogisanobatonasumibunasushiobaranishikatautsunomiyaiwafunemashikoshimotsukeohtawaratakanezawaitanokomatsushimatokushimaichibaminamiaizumiwajikikainanmiyoshinarutomimamugiananmatsushigesanagochishishikuinakagawamachidachiyodakomaefussainagitaitochofufuchuomeotahigashiyamatotoshimaokutamaaogashimakodairaedogawaarakawahachiojishinagawatachikawashibuyasuginamihinodekiyosesumidaoshimanerimamitakahamuraadachinakanomizuhobunkyomegurominatokoganeihigashikurumekokubunjihigashimurayamamusashimurayamatamakitahinochuokotokatsushikakouzushimaogasawaraakishimakunitachishinjukusetagayamusashinohachijoitabashiakirunohinoharachizunanbukotouramisasawakasayonagokogehinoyazutottorinichinansakaiminatokawaharaoyabetairainamiasahinantoimizufuchutakaokakurobeyamadajohanatoyamatonaminyuzenfunahashinakaniikawanamerikawaunazukitogahimiuozufukumitsutateyamakamiichiiwadearidayuasainamitaijikatsuragiaridagawatanabemihamahidakakainankiminomisatoshingushirahamakamitondayurakozakoyagobokitayamawakayamakudoyamahashimotokushimotokozagawahirogawakinokawanachikatsuurarsuseroeoishidasagaeoguniasahinagaitendonanyoobanazawanishikawasakataohkuratozawamikawamamurogawayamagatafunagatatakahatashonaishinjokahokuiideyuzakawanishitsuruokakaminoyamayamanobeshiratakamurayamanakayamakaneyamahigashineyonezawasakegawamitouubeyuuabushimonosekitabuseoshimatoyotaiwakunihikarishunannagatohagihofukudamatsutokuyamashowadoshitsurunanbukoshukaiminami-alpsnirasakikosugeotsukioshinohokutominobuyamanashifuefukichuokofuichikawamisatoyamanakakonakamichitabayamanishikatsuranarusawafujikawahayakawafujiyoshidafujikawaguchikouenohara長野京都岐阜大阪三重群馬千葉滋賀佐賀奈良adednelgaccogogror秋田愛知高知埼玉沖縄栃木熊本岩手青森山梨新潟島根鳥取長崎香川宮城石川大分宮崎茨城山口兵庫山形徳島広島福島福岡岡山富山静岡愛媛福井東京xn--4it168dhatenadiaryxn--vgu402ckawaiishophatenablogcocottenamaste北海道penneehimeiwateversestabachibashigagonnagunmapermahaccaakitaosakauh-ohblushkochiaichifukuikuroncapooitigohyogotokyokyotopunyuthickcheap0t00g00j0mie2-ddaapyawjg0amfemsubxiiboomoobutchueekpgwrgrherskrboyrdyupperunderflierchipsmydnsheavyangryhippygirlyrulez神奈川鹿児島和歌山bambinaxn--nit225kokayamasaitamaxn--k7yn95exn--1lqs03nsapporoparasitelolipopmcxn--efvn9sniigatafukuokatokushimafukushimahiroshimakagoshimafakefurokinawaxn--8pvr4ucoolblogxn--0trq7p7nnkawasakinagasakimiyazakichilloutxn--8ltr62kxn--klty5xpeeweezombiecutegirlxn--rny31hxn--uuwu58axn--ntso0iqx3axn--djrs72d6uytoyamanikitanyantakagawamimozanagoyaboyfriendxn--2m4a15egreaterchowderegoismyamagatafashionstorexn--elqq16hxn--pssu33lsendaimiyagixn--rht27zpecoriaomorisaloonwatsonvivianxn--djty4knobushipigboatnaganopinokoxn--f6qx53asadistvelvetsecretxn--5js045dchicappayamanashiibarakidigickgirlfriendxn--1lqs71dmongolianxn--c3s14mxn--qqqt11mtochigixn--5rtq34kparallelo0o0mondkobesagabonadecaoitanarafoolkilldecimainhiholomosblokilociaoundopupugifutankcrapflopnooroopsmodsholyjeezstripperpepperbittershizuokaxn--rht3dkitakyushureadymadeicurusversusmatrixxn--rht61ehungryfloppygloomycrankyhandcraftedlittlestarxn--klt787dxn--kltx9awhitesnowsunnydaytottorilovepoptheshopbuyshopxn--5rtp49cxn--d5qv7z876cwebaccelxn--kbrq7oxn--4pvxsxn--1ctwolovesickkumamotocatfoodxn--tor131oyokohamawakayamatonkotsuxn--ehqz56nxn--uist22hxn--6btw5axn--kltp7dyamaguchifrenchkisspussycatxn--4it797kxn--uisz3gbabybluexn--zbx025dnetgamersxn--7t0a264ckanagawaxn--6orx2rishikawaxn--ntsq17ghalfmoonschoolbusjellybeanxn--mkru45iusercontentlolitapunkxn--32vp30hsakurastoragehokkaidoshimanecandypopbabymilksupersaleweblikeraindropbackdropwebsozaikikirarahateblodaynightmeneacsccogoormobiinfoaeusxxorgmilcomnetedugovorgcomnetedugovbizinfotmprdorgmilcomnomedugovassnotairespresseassocoopgouvveterinairemedecinpharmaciensorgnetedugovtraorgcomedurepgovmeneperekgacscaiiocogoitoresmshsseoulbusanulsandaeguc01milvkimmvchungnamjeonnamjeonbukeliv-dnsgyeonggijejueliv-cdnincheondaejeongangwongyeongbukgwangjuchungbukgyeongnameliv-apicoeduindorgcomembnetedugovorgmilcomnetedugovjcloudorgcomnetintedugovperbnrinfocooyorgcomnetedugovethipfscanvamypepethw3sstorachakeeneticjoinmcinbrowserdwebcyonnftstoragemyfritzaemewphlxachotelltdorgcomwebsocschngonetintedugrpgovassnomgacsccoorgnetedugovbizinfo123websiteidorgmilcomasnnetedugovconfidmedorgcomplcschnetedugovaccoorgnetgovpresstmassoirseproxaccosoundcasthoptocraftvp4c66orgnetedugovitsmcdirmyboxbarsyedgestacksynologylogintoopencloudnohostwebhopdiskstationi234tcp4hoocgroknoipprivmydsddnsdnsforlohmustransipdscloudfilegear-sgbrasiliafilegearframerbarsybarsyonlinecoprdorgmilcomnomedugovinforgcomnetedugovnameacprorgcomartnetedugovpresseinfoassoinstgouvorgnycedugovbarsydscloudjuorgcomnetedugovminisiteaccoororgcomnetgovorgmilcompronetintedugovbizmuseumnameinfoaerocoopaccoorgcomnetintedugovbizcooporgcomgobneteduorgmilcomnetedugovbiznameaccoorgmilneteduadvgovcoorgcomnetaltgovforgotherhiskeeneticispmanagernomassoprod5476132eastasiacentraluswesteuropewestus2eastus2pnortheurope-01newzealandnorth-01southindia-01southcentralus2-01norwaywest-01eastus2-01westus2-01australiaeast-01italynorth-01israelnorthwest-01swedencentral-01westeurope-01centraluseuap-01taiwannorthwest-01uaecentral-01northcentralusstage-01israelcentral-01mexicocentral-01canadacentral-01austriaeast-01germanywestcentral-01francecentral-01ukwest-01denmarkeast-01polandcentral-01eastus-01westus-01swedensouth-01eastus3-01westus3-01brazilsouth-01centralus-01francesouth-01australiacentral-01westindia-01uaenorth-01jioindiacentral-01canadaeast-01belgiumcentral-01spaincentral-01koreacentral-01chilecentral-01qatarcentral-01westcentralus-01eastus2euap-01norwayeast-01southafricanorth-01brazilsoutheast-01germanynorth-01switzerlandnorth-01switzerlandwest-01japanwest-01southafricawest-01japaneast-01eastasia-01indiasouthcentral-01taiwannorth-01centralindia-01uksouth-01southcentralus-01northcentralus-01eastasiastage-01indonesiacentral-01australiacentral2-01australiasoutheast-01malaysiawest-01koreasouth-01southeastasia-01southeastus5-01northeastus5-01jioindiawest-01rucdnwest1-usfra1-desandboxjls-sto1jls-sto3jls-sto2aglobalabglobalsslmapprodfreetlsmapvpslon-1lon-2ny-1fr-1sg-1ny-2paassnwebpaashostingjelasticnordeste-idcsocuserpagescwebfileblobservicebuscoreatlricnjsjelasticwebsitestoragesezagbinruhuukjptsmyspreadshopmynetnameakamaiorigin-stagingfrom-coipv64dynv6cdn77serveblogadobeaemcloudhicamsprytdnsupno-ipownipde5ovhicpfirewall-gatewaysytesmypsxbarsyusgovcloudapimyamazemyradwebakamaihdsaveincloudfastlylbfrom-lasubsc-paysquare7in-the-bandblackbaudcdnhomelinuxoninfernoctfcloudservebbsdns-dynamiccloudfrontakamai-stagingipifonyham-radio-opsenseeringclickrisingcommunity-profrom-nylocalcertgrafana-devedgesuite-stagingcloudflareanycasteating-organicatlassian-devmydattofeste-iplocaltotorprojectknx-serveredgekeycloudflareglobalcloudyclustercasacamserveftpakamaized-stagingakamaiorigindns-cloudmyeffectboomlabotdashbuyshousestwmailhetemlazure-mobilein-dslthruhereredirectmedynuddnsbouncemesupabaseluyanicloudappakamaicloudfunctionsdebiannhlfanpgafanstatic-accessin-vpnmysynologymafeloappudohomeftptrafficmanagersiteleafseidatmemsetcloudflarecloudaccesskeyword-onazure-apiis-a-chefdoes-itgets-itwebhopselfiphomeipkicks-assedgesuitewindowsserver-ontunnelmolemydissentscrapper-sitecloudflarecnuni5srcfggffiobbzabchrsndenodynuopikddnsvpndnsakadnselastxkinghostvps-hostfastlyhomeunixazureedgeshopselectdontexistmyfritzcloudjiffyalwaysdatasells-itsquaresbroke-itazurefddattolocalat-band-campmeinforumfamilydsazurestaticappsdefinimabplaceddnsaliasdynaliasnow-dnsblogdnsroutingthecloudendofinternetdsmynasakamaiedgemymediapcadobeio-staticakamaiedge-stagingakamaihd-stagingddns-ipprivatizehealthinsurancelive-onkrellianschokokeksmassivegridmysecuritycamerarackmazeserveminecraftfrom-azis-a-geekakamaizedmoonscaleoffice-on-theusgovtrafficmanageradobeioruntimeedgekey-stagingreserve-onlinechannelsdvrdnsdojousgovcloudappcdn77-sslapps-1and1podzoneazurewebsitesdynathomescaleforceyandexcloudvusercontentisa-geekcdn-edgescoaemalcesappwriteazimuthtlonarvobuiltwithrocketnoticeablestorecomwebrecnetperotherfirminfoartslgdloncogoiltdorgmilcolcomplcschgenngonetedugovbiznamefirmmobiacincoorgmilcomnomwebgobnetintedubizinfocomyspreadshopdemongovtransurl123websitehosting-clusterkhplaycistrongsnesosvalervålerxn--vler-qoaossandeheroysandeherøybøboheroyherøyxn--hery-iraxn--b-5gavalerbøboxn--b-5gasandesandexn--hery-iraxn--vler-qoavålerhåreålaahavaofsfvfhlolnlalrlhmfmtmahcostntbuåstrmreigersundmyspreadshopgálsáeidsvolltingvollgildeskalflorøvadsøvardøvanylvenxn--bhccavuotna-k7astrandaxn--kvnangen-k0axn--sknland-fxaxn--mosjen-eyarakkestadhyllestadnannestadvevelstadvaapstenordre-landsondre-landsøndre-landtjieltexn--vrggt-xqadsør-aurdalsor-aurdalheradstordmoldefordeførdeseljefedjeryggehemnexn--krehamn-dxasognegranesøgnebrynetjomevallebykletokkegiskedovretjømehobølvoldasaudatolgasømnaviknadønnasomnadonnatranafrananesnaraumasmolatrænafrænalesjasmølaørstaorstahitrafloraaukraloppafrøyarissasnasahalsagalsaromsaraisaráisafroyasnåsagronghobolfjelltydalårdalardalaskimharamkraanghkekråanghkesorumbarumhurumbærumsørummodumsálátbálátfrognbjugnvåganvagangulenskienløtenlotenstrynvefsnxn--merker-kuaskaunsveiobømlobomloskjåkvardoflorovadsosalatbalatsálatklæbuklabuselbubarduulvikskjakklepprisørxn--nttery-byaeflåeidflahofmilgolholsellomskifetvikdepvgsfhsaskerrisorhamarasnesåsnesrørosrorosxn--slat-5namasoynaroyvaroyluroydyroyaskoyradoyandoyrodoymeloyradøyandøyrødøymeløyaskøylurøydyrøymåsøyværøynærøyhoylandethøylandetdivtasvuodnalørenskoglorenskognesoddtangenxn--tjme-hraxn--smla-hraxn--stjrdal-s1aunjargalillehammerunjárgaxn--hamary-fyadavvenjargaxn--bearalvhki-y4a123hjemmesidegjerdrumxn--brnnysund-m8acxn--tnsberg-q1axn--mlatvuopmi-s4axn--snsa-roaxn--skierv-utaxn--brum-voatysfjordkvafjordeidfjordkvæfjordsongdalenmjondalenmjøndalenxn--gls-elackragerogáŋgaviikagangaviikasørreisasorreisasør-varangersor-varangerxn--risr-iraskiervaxn--frna-woaxn--trna-woakvinesdalleksvikleirvikrøyrvikroyrviksvelvikvenneslaevje-og-hornnessandnessjøenmarnardalvindafjordsandefjordenebakksnillfjordullensvangxn--trany-yuabrønnøysundnamsskoganaustevollxn--stjrdalshalsen-sqbnord-aurdalnord-frontrøgstadtrogstadgrimstadflakstadgjerstadxn--sandy-yuaxn--leagaviika-52bnore-og-uvdalvegarsheixn--rlingen-mxaxn--ggaviika-8ya47hvegårsheikarlsoykvitsoymasfjordenhamaroyinderoyosteroydavvenjárgasauheradguovdageaidnuxn--vre-eiker-k8abronnoysiellakkrødsheradkrodsheradkvinnheradbrønnøyxn--mtta-vrjjat-k7afxn--lrenskog-54akvitsøyvárggátkarlsøyosterøyinderøyhamarøybronnoysundxn--aurskog-hland-jnbbahccavuotnabáhccavuotnagiehtavuoatnastor-elvdalmidtre-gauldalxn--gildeskl-g0akarasjokevenassixn--bievt-0qaxn--yer-znalebesbynessebyxn--hbmer-xqamalselvmålselvxn--unjrga-rtamøre-og-romsdalmore-og-romsdalhareidmelandørlandorlandstrandålgårdsolundalgardafjordåfjorddielddanuorrikautokeinoxn--stre-toten-zcbskodjeaejriestangeliernebamblestokkefauskesnåasesnaasekongsvingerlangevagberlevagxn--flor-jrahattfjelldalostre-totenøstre-totenvestfoldxn--mely-iraálaheadjualaheadjunordreisaxn--troms-zuaxn--lgrd-poacporsangerflatangerstavangerleikangerbremangersamnangergieldakarasjohkaxn--rdy-0nabfrostautsirasnoasatromsaxn--sr-aurdal-l8aflekkefjordjølsterjolsteraremarkhedmarknååmesjevuemienaamesjevuemiexn--vard-jrarollagmeråkermerakerorskogørskogxn--bdddj-mrabdákŋoluoktaxn--osyro-wuaaknoluoktatrysilskjervøymandaljondalbindalrindalmeldalsuldalorkdalsigdalalvdallærdalhurdalsirdalverdallerdallardaloppdalåseralaseralhadselkragerødivttasvuotnaoverhallasteinkjerxn--hnefoss-q1askedsmokorsettromsøxn--dyry-iravestre-totenmuseumxn--sandnessjen-ogbrahkkeravjufylkesbiblbájddarbajddarxn--laheadju-7yarennesøyxn--koluokta-7ya57hxn--hgebostad-g3aleirfjordstorfjordbalsfjordbåtsfjordbatsfjordmuosátbievátloabátkárášjohkanøtterøyxn--mjndalen-64anordkappláhppilahppialstahaugsiljanverranrøykenroykenhaldenlyngenbergenhortenhønefosshonefosstroandinbeiarnvarggatosoyroosøyrotromsoidrettmuosatbievatruovatloabatvoagattynsetnessetxn--indery-fyaskánitskanitraholtråholtxn--ystre-slidre-ujbandebusarpsborgbearduxn--karlsy-fyahordalandjorpelandjørpelanddeatnuringsakersør-odalsor-odalxn--slt-elabringerikeaudnedalnittedalnissedalhemsedalslattumsurnadalxn--blt-elabelverumstjørdalnaustdalhjartdalgjøvikfyresdalhasviknarviklarvikgjovikmalvikgamviklenvikporsgrunnstjordalengerdaldrobakdrøbakxn--msy-ula0hvestvagoyxn--vgan-qoaxn--ryken-vuaxn--lten-graxn--stfold-9xaxn--hpmir-xqaxn--lury-iramálatvuopmimalatvuopmitysværkirkenesbirkenesmoskenesbáidárxn--fjord-lraxn--rdal-poabahcavuotnabáhcavuotnaxn--frde-gralindåsbearalvahkixn--hobl-iraráhkkerávjuxn--loabt-0qavågåáltábodøsundlundraderådeetnetimeholeauregrueoddavagavegaranatanaarnasolasulaaltalekafusavangbergkvamåmliamlibokntinnroangranosenoslobodorøstroststatåmotamotivguprivøyeroyerliermossvossxn--nvuotna-hwalusterlunnermarkerhábmerhabmerhvalerfjalerxn--rholt-mratysvarbaidarfitjargaularhápmirhapmirmelhusfosnesøksnesoksnestysneshemnesevenesflesbergeidsbergtonsbergtønsberglindasxn--sndre-land-0cbnamsosxn--srum-graøystre-slidreoystre-slidrevestre-slidretrondheimbalestrandxn--langevg-jxaaustrheimxn--skjk-soavagsoyaveroysandoykarmoyfinnoytranoyvestbytranbysykkylvenxn--hyanger-q1aspjelkavikandasuoloxn--fl-ziaxn--drbak-wuastathellexn--sr-varanger-ggbtelemarkxn--bhcavuotna-s4axn--porsgu-sta26fčáhcesuolocahcesuoloakrehamnåkrehamnsandøykarmøyfinnøytranøyvågsøyaverøynamdalseidxn--lesund-huabadaddjaxn--vegrshei-c0axn--btsfjord-9zagildeskålporsanguxn--trgstad-r1anávuotnanavuotnahammerfestxn--sgne-graxn--brnny-wuacibestadharstadnarviikaevenáššivestnesgjemnessandnesagdenesrennesoyxn--avery-yuaxn--tysvr-vrabearalváhkikongsbergspydebergrandabergxn--andy-iradavvesiidaxn--krdsherad-m8aporsáŋgufredrikstadbjerkreimringeburennebuaurskog-holandnotteroyxn--vgsy-qoa0jxn--rmskog-byaskierváivelandbyglandfrolandaurlandforsandxn--bjddar-ptamidsundålesundalesundfetsundfarsundovre-eikerøvre-eikerakershusxn--moreke-juasørfoldøstfoldostfoldsorfoldhøyangerhoyangerlevangerorkangertanangerxn--vestvgy-ixa6olillesandulsteinxn--rennesy-v1agranvinskjervoyxn--klbu-woalavagisxn--h-2faxn--ryrvik-byakafjordkåfjordseljordfolkebiblxn--gjvik-wuajevnakerxn--kfjord-iuabudejjuxn--kranghke-b0axn--davvenjrga-y4axn--rland-uuaxn--ldingen-q1axn--mlselv-iuaxn--rady-iraxn--linds-prabrumunddalxn--ygarden-p1amo-i-ranaeidskogrømskogromskoghjelmelandxn--finny-yuaxn--sr-odal-q1axn--skjervy-v1aballangenkvanangenkvænangengratangenxn--hmmrfeasta-s4acvossevangensuohkanxn--rde-ulaxn--mli-tlaxn--ksnes-uuanordlandskanlandskånlandsortlandfuoiskuxn--rros-graxn--hcesuolo-7ya35bxn--eveni-0qa01gagaivuotnagáivuotnaxn--seral-lradrammenmodalenmosjoenjan-mayentorskensteigengloppenxn--snes-poamatta-varjjatxn--sr-fron-q1aomasvuotnajessheimbådåddjåxn--krager-gyaxn--kvfjord-nxaxn--asky-iraxn--snase-nraxn--bidr-5nacholtålenxn--vads-jraxn--jlster-byamosjøenxn--rst-0nastavernxn--ostery-fyaxn--oppegrd-ixaxn--sknit-yqaxn--risa-5naoppegårdskiptvetrendalenholtalenxn--mot-tlaxn--lhppi-xqaxn--holtlen-hxaxn--srreisa-q1akopervikxn--muost-0qaxn--bmlo-grahokksundkvalsundegersundxn--karmy-yuaullensakerxn--hylandet-54axn--kvitsy-fyaxn--bod-2nalangevågberlevågkristiansandxn--rsta-frahornindalstjørdalshalsenstjordalshalsensandnessjoenhámmárfeastaxn--lrdal-srasør-fronsor-fronnord-odalkristiansundmátta-várjjatvestvågøynesoddennotoddenbuskerudøygardenoygardensalangenlavangenralingenrælingenlodingenlødingenleaŋgaviikalaakesvuemieleangaviikauenorgexn--srfold-byaaskvollxn--rskog-uuaxn--nry-yla5gxn--vry-yla5ghammarfeastaxn--rhkkervju-01afxn--givuotna-8yakommunekrokstadelvanedre-eikerhagebostadhægebostadxn--berlevg-jxakviteseidxn--s-1faxn--l-1faxn--nmesjevuemie-tcbafuosskomoårekemoarekexn--lt-liacxn--jrpeland-54asvalbardoppegardholmestrandtvedestrandsogndalsokndalarendalsunndalfolldalxn--krjohka-hwab49jlyngdaletnedalnorddalsaltdalgausdalskedsmovaksdalgjesdalstordalxn--frya-hraaarbortedrangedalxn--smna-graaurskog-hølandxn--vg-yiabtjeldsundhaugesundlindesnesxn--mre-og-romsdal-qqbxn--dnna-gradyntmpheremerseineshacknetenterprisecloudmineaccomaorimāoriorgmilcriiwigennetschoolhealthkiwigovtgeekxn--mori-qsacloudnsparliamentcomedorgcompronetedugovmuseumwebsitekinservicebarsywebsitebuildereerobookheimdnsleapcelleero-stagetechcrscsslorigingohomecdbedeeeiemesecabgngilnlalplchfisiincnnoroptatitmtltruauhulumkdkukskjplvtrgrfrkrhrusesismycynzcznetinteduassoososcloudstgbetaaezaeuhkusjshatenadiarycdn77hoptozaptois-a-knightmyftpno-ipjpnddnssdpdnsspdnsbarsysweetpepperis-a-bruinsfanis-very-sweetservegameis-a-soxfanhomelinuxcdn77-secureservebbsmisconfusedwebredirectblogsitefreedesktopcouchpotatofriestoolforgeaccesscamis-lostreadmyblogsmall-webfedorapeopleserveftpis-a-celticsfanmywirepotagertwmailin-dslsellsyourhomeread-booksfreeddnscable-modemis-savednflfanufcfanmlbfanstuff-4-saleendoftheinternetin-vpnmy-firewallhomeftpis-localis-a-chefboldlygoingnowherewebhopselfipkicks-assroxatunkcamdvrfedoraprojectgotdnsdvrdnsdyndnspubtlspimientahomeunixdontexistfedorainfracloudwmflabsfspagesbmoattachmentsteckidsfamilydsdnsaliasdynaliasnow-dnscloudnsdoomdnsduckdnsblogdnshomednsroutingthecloudendofinternetdsmynasip-dynamicpoivronhttpbinmyfirewallis-very-evilmysecuritycamerais-a-linux-userwmcloudis-a-geektuxfamilyis-a-candidatedoesntexistis-very-badhobby-sitegame-hostaltervistais-foundis-a-patsfandnsdojohepforgepodzonedynservcollegefanis-very-goodfrom-meis-very-niceisa-geeknerdpolacmedsldingorgcomnomgobabonetedupleskaemhlxmyboxrockyprvcydeuxfleurspdnscodebergheyflowstatichostorgmilcomnomgobneteduorgcomeduiorgmilcomngonetedugovcloudns1337ngrokacorggogfamcomwebgobnetedugokgopgkpgovgosbizpasaugumicsopozpapuwmwsrprusiskwpspkppspkmpspokeoiawsawifoumsdnskokwpmuppuppsppiwwiwoowuzswkzoschrzpisdnwzmiuwwitdpssewsseumigugimoirmpinbwinbwiihupporzgwgriwupowwskrwioswuozstarostwokonsulattmpccopruszkowmyspreadshopostrodakartuzyopolegminamediaustkazgorajgoraolawailawalomzawloclradombytomjaworznotargilubinkoninzagantorunkutnokepnonakloczestsopotsanokturekplockslasksklepzarowlukowmedaidgdaorgmilrelcomnomatmgsmartneteduelkgovwawsossexbiztgorysejnytychypomorzeboleslawiechomesklepsdscloudunicloudzakopanelegnicarawa-mazbydgoszczswidnikkrasnikwloclawekbielawamragowograjeworealestatebeskidykaszubymalopolskaprzeworskswiebodzinlecznadfirmaszkolawarmiagdyniamiastakazimierz-dolnymalborkswidnicadlugolekaostrolekapodlasieelblagtravelsimplesitezachpomormielecszczecinnieruchomosciwalbrzychlezajsklublinbedzinpoznanwielunmielnooleckostarachowicedkontopowiatwroclawrybniksuwalkileborkslupskgdanskostrowwlkptarnobrzegtourismwegrowkrakowglogowyou2pilanysamailwrocinfoagroautobeepshopprivlapypiszlodzcfolksecommerce-shopmazurypulawyskoczowrzeszowpomorskiezgierzkaliszolkuszlowiczostrowiecsosnowiecmazowszewodzislawbialowiezazgorzeleckatowicepabianicejelenia-gorawolominkarpaczsieradznowarudaczeladzkonskowolaskierniewiceswinoujscieturystykabieszczadycieszynketrzynolsztynbialystokbabia-goraprochowicewarszawastalowa-wolapolkowicegorlicegliwiceponiatowalimanowalubartowaugustowkobierzyceopocznognieznoszczytnokolobrzegshoparenapodhalebielskoklodzkostargardatwithplayitownnamecoorgnetedugovacorgcomproestnetedugovbiznameislaprofinforechtngrokmedaaaacacpaenglawjurbarbarsykeeneticavocatacctcloudnsorgcomsecplonetedugov123paginaweborgcomnetintedugovnomepublidkinbarsygovx443cloudnsorgmilcomnetedugovcooporgmilcomschnetedugovnamecomcannetlibassoaemclantmcontstoreorgcomnomrecwwwbarsyfirminfoshopartsstackitmyddnswebspacelima-cityacincooxorgedugovbarsybrendlyhbvpsvpsspectrumlandinghostingacppmordoviamcprecbgorgmilcomspbnetintedumsknovgovbirrasmcdirmytismircloudvladimirnalchikadygeyamarinepyatigorskmyjinobashkiriaeurodirvladikavkazna4ugroznykustanaikalmykiacldmaildagestaniranbuildcloudcanvaliaravalwixdevelopmentappwritemigrationneedleverceldatabasestackitcodereplravendbonporterlovableaccoorgmilnetgovcoopmedorgcompubschnetedugovservicemecomygovorggovtvmedorgcomnetedugovinfoedgfacbmlonihkutwpsryxzbdtmacfhppmyspreadshopbrandpartiorgcomfhvpress123minsidaitcouldbeworlanbibkommunalforbundfhskiopsyskomvuxkomforbnaturbruksgymnloginlineorgcomnetedugovenscaledeuusentsurgebotdaorgmilcomnetgovnowteleporthashbangplatformlovablebarsyshopwarebasehoplixbarsyonlinemsf5gitappgitpagewawamscofigma-govcaffeinefigmacanvasoltstscwputerbarsysupportchatgptsquareomniweopensocialcpanelplaycodenotionnovecorewpsquaredpreviewjelecyonbyensrhtfastvpspieboxconvexjouwwebheyflowplatformshloginlinemadethissourcecraftclouderaorgorgcomartedugouvunivmeorgcomnetedugovsurveysstatichfheiyuxs4allprojectmyfastubervibehostapp-ionosdeployagentmecoorgcomschnetedugovbizcncostoreorgmilcomneteduembaixadaconsuladokiraranohoprincipesaotomeheliohobarsystorebaseshopwaresellfyaiabkhaziavologdamordoviapenzalenugsochinavoiexnetspbmsknovnorth-kazakhstanashgabadkareliaarmeniageorgiavladimirnalchikivanovobukharaadygeyakhakassiakalugakrasnodarjambylaktyubinsktroitskbryanskobninskkurganazerbaijanpokrovskbashkiriatselinogradvladikavkazmurmansktulatuvamangyshlaktashkentchimkentgroznykaragandatermezarkhangelskkustanaikalmykiabalashoveast-kazakhstankaracoldagestantogliattibarsyredorgcomgobedumirenknightpointaccoorgjelasticdiscoursecleverappsschacmiincogoornetonlineshopcogoorgmilcomwebnicnetintedugovbiznametestcoorgmilcomnomnetedugovorangecloudpersoindorgcomfinnatnetgovensmincomtourismintlinfox0611oyaorgmilcomnetedugovquickconnectvpnplusnettprequalifymeaddrmyaddrntdllwadlnctvavdrk12orgmilpolbeltelcomwebgennetedutskkepgovbbsbiznameinfocoorgmilcompronetedugovbiznameinfobetter-thanworse-thansakurafromdyndnson-the-webmymailerorgmilurlcomneteduidvgovmydnsgameclubebizmeneacsccogotvorhotelmilmobiinfovodteiflgplkmsmsbcckhincndnvncoztltmkckppzpdprvcvkvlvcrkrkscxuzchernovtsyrivneyaltaodesavolynrovnolutskltdinforgcomnetedugovbizvinnicazhitomirternopilpoltavakropyvnytskyizaporizhzhiasevastopolsebastopoluzhgoroduzhhorodkharkovkharkivvinnytsiakhmelnytskyizaporizhzhecrimeaodessazhytomyrnikolaevcherkassydonetskluganskluhanskkirovogradivano-frankivskchernivtsikrymkievkyivlvivsumyzakarpattiamykolaivcherkasychernigovkhersonchernihivdnipropetrovskdnepropetrovskkhmelnitskiyneacsccogoorusorgmilcomedugovmyspreadshopadimono-ipbarsybarsyonlinelayershiftnh-servretrosnubapicampaignservicelugaffinitylotteryweeklylotteryraffleentrygluglugsmeaccoindependent-inquestnimsitecopropymntltdorgplcschnetgovnhsbarsyindependent-commissionindependent-reviewpolicepublic-inquiryindependent-panelconnhospindependent-inquiryroyal-commissionoraclegovcloudappscck12libaws-govccphxcclibpvtparochchtrcck12libcceatonk12coglibtecgendstmusann-arborwashtenawcck12glghcck12sealibforksolympiabainbridge-islkeyporthoquiamyarrow-pointcentraliaport-townsendsequimport-ludlowrentonsilverdalebremertonredmondsheltonbellevueport-orchardport-angeleskingstonchehalisaberdeengig-harborseattlepoulsboidmdndsddemenegacalamaiavawapailalflnmdcncscohnhmihiviwiriinmntnmocoutvtctmtgunjokakwvnvprarorasmskstxwynykyazisadninsnngosrvis-bymircloudservernamepointtoenscaledland-4-salefreeddnsstuff-4-saleazure-apinoipdatabricksappscloudnsgolffanheliohostazurewebsitesgvorgmilcomgubneteducoorgcomnetd0egvorgmilcomnetedugovmydnsiacostoree12orgmilcomnomwebgobbibrectecnetintedugovraremprendefirminfoartseducok12orgcomnethidnsidacaiiosonlahanamhanoicamauhueorgcompronetintedugovbizbacninhtayninhhoabinhnamdinhtravinhhaiphongvinhlonghaiduongquangnamquangtrithuathienhuequangninhbacgianghaugiangquangbinhsoctrangbentrethanhphohochiminhdanangkontumhatinhkhanhhoathanhhoahealthgialailaocaiyenbaibackanngheanlonganphuyenphuthocanthodaklakdongnainameinfovinhphucdongthapkiengiangtiengiangquangngailaichaulangsonlamdongdaknonghagiangangiangcaobangbinhduongninhthuanbinhthuanbaclieuthaibinhninhbinhbinhdinhtuyenquanghungyenbaria-vungtauthainguyendienbienbinhphuocschbizputerimagine-proxyorgcomnetedugovcloud66advisormypetsdyndnsxn--8dbq2axn--4dbgdty6cxn--5dbhl8dxn--hebda8bxn--80auxn--d1atxn--c1avgxn--o1acxn--o1achxn--90azhxn--55qx5dxn--uc0atvxn--od0algxn--wcvs22dxn--gmqw5axn--mxtq1mxn--12c1fe0brxn--h3cuzk1dixn--12co0c3b4evaxn--12cfi8ixb8lxn--o3cyx2axn--m3ch0j3axn--j1adpxn--90amcxn--90a1afxn--h1ahnxn--j1ael8bxn--h1alizxn--c1avgxn--j1aefxn--80aaa0cvacxn--41acaffeineexeopentunnelbotdashtelebitorgtmaccoagricorgmilnomwebnicngonetaltedugovlawnisschoolgrondaraccoorgmilcomschnetedugovbizinfoprg1-zeropstritonstackitlimazeropsaccoorgmilgovяспборгкоммскбизмирсамаракрымсочиакодпроргобрупрצהלממשלישובאקדמיהองค์กรธุรกิจรัฐบาลศึกษาทหารเน็ต教育網絡組織公司政府個人닷넷한국澳门新闻澳門联通家電嘉里招聘通販닷컴삼성コムგეбгрфеюadcdbdgdidmdsdtdaebedeeegeiejekemenepereseveyegabacalamanauavapaqasazacfbfafgfnfpfwftfbgcgagggegkgngmgsgpgvgtgugilmlnlalclglplsltlhmimjmkmmmomambmcmdmfmgmzmpmsmtmgbbblbsbecccacnclcmcvctcscmhkhghchbhthphshlinikifigiaibicivisikninhnmncnbngnsnpnvntnjoionomobocoaofodorosotoptstttytatbtetgtithtmtltrusuvuaucueuguhulumunufjdjbjtjsjlkmkhkfkdkcktkukskpkgpmpnpkpjpgqaqmqiqsvtvcvbvmvlvrwpwtwzwbwcwawgwkwmwtrsrprgrfrercrbrarnrmrlrkrirhrwsusrssspsgsesbsaslsmsissxmxaxcxuypysylymykygybycyuztzsznzmzkzdzczbzazελευ世界台灣购物公益点看臺灣网络書籍在线网站手机机构大拿游戏信息台湾谷歌慈善商标香港中国餐厅网址中國商城食品微博政务移动集团公司八卦商店健康网店政府时尚佛山中信娱乐广东企业homedepotengineeringاماراتrepublicankuokgroupversicherungchannelcitadelxn--pgbs0dhxn--b4w605ferdstatebankwebsitexn--mgb9awbf亚马逊淡马锡alibabaxn--ngbc5azdxn--mgbbh1axn--45br5cyltoshibabuildworldcloudtradeguideplacespacedancemoviephoneprimesmilebiblestyleappleazurestoreskypegripexn--l1accdrivelottehorsehouseleasechasereisestadahondaomegaaetnaamicaninjanokiamediadeltavodkaedekaosakapizzaslingemailgmailtirolshelltmallfinallegaltotalhotelamfamforumrehabmusicciticricohcoachwatchboschearthfaithirishmiamiarchidubaiguccipraxiみんなストアセールcanonsalononionnikonepsonkoelngreensevencrownikanoradioaudioweiboglobopromogalloyahoociscorodeovideomangobingotokyovolvolottokyotophotosmartsportquesttrusthyattjetztadultcymrubaidutushuxn--kprw13dubankclickblackmerckgroupsharpcheapnowtvxn--h2brj9cקוםհայоргсрбмонкомбелмкдқазрусукрمصرقطرعربكومdadcfdmedwedredphdthdbidpidkrdmsdltdiceonewmeglemoerwecfageacbanbambaaaammakianraspacpaaxawtfbcgaegongingaigvigorgdogdhlmilrilonlaolloluoljllcalgalnflafltelsrlfrllplkimibmcamcombommomifmabbjcbscbwebcabnabtabmlbpubabcbbcnecincpncllcstcwtcpwcnyckfhbzhovhmoiskiobisbitcifyituipinvinwinxincbnbcnmanfangdnmenrenkpnmtnyunrunfununobiojioriohbogmofooboooooacoecoceongoproartistottnttbbtcateatlatvetpetbetnethktmitfitintjothotgotdotbotprueduicujnjyouinknhktdkappsapgapmapdnptopgopllpjmpzipvipripesqtrvdtvitvdevmovgovhivnrwlawsewnewbmwwownowhowdvrftrmtrsfrbarcartvscrseusawsupsubssbsadsddsldssasbmsmlsxxxboxfoxgmxtjxsextaxbuyflydiysoyjoyskypaydaygayxyzanzbizwebersenerpokerlameractortatarsolarລາວคอมไทยtourslocusnexuslexusgiftsbeatsboatspartspressglassswissकॉमनेटtiresgivescodeshomesgamestunesshoescardswalesloansvegastoolsdealsautosparisファッションworkssucksrocksxeroxforexfedexpartylillymoneystudyrugbytoraytoday中文网xn--unup4y天主教飞利浦新加坡enterprises我爱你嘉里大酒店christmasxn--fct429kholdingsxn--8y0a063axn--mgbx4cd0ablifestyleabogadoallstatenetbankكاثوليكxn--s9brj9cxn--gk3at1ebestbuycharityxn--55qx5dmicrosoftpropertybasketballhomegoodscorsicajewelrygallerygrocerysurgerycountrybrusselsverisignferreroxn--czr694bhdfcbankcommbanksoftbankپاكستانپاکستانnextdirectالسعوديهالعليانxn--h2brj9c8cxn--80adxhksshikshaxn--mgbai9azgqp6jcuisinellabarclayscatholicxn--kpry57dcompanyxn--xhq521bblackfridayxn--mgba3a3ejtsandvikxn--d1acj3bacademydownloadمليسياxn--j1amhxn--w4r85el8fhu5dnraipirangaathletaxn--fhbeixn--mgbqly7cvafrzuerichxn--c2br7gஇலங்கைcontractorsxn--io0a7igraphicsinsurancetemasekxn--xkc2al3hye2amotorcyclesphotographydirectoryplumbingxn--vhquvclothingtrainingcleaningwilliamhilllightingxn--mgba3a4f16ashoppingcateringeducationokinawapicturesventuresproductionsxn--9et52uwalmartഭാരതംsupportrealestatecapitalonexn--nqv7fs00emaauspostfloristdentistxn--qxamgodaddybradescobargainsmitsubishikerryhotelsxn--9dbq2axn--3pxu8kimmobilienxn--fjq720axn--mgbtx2bholidaymckinseymadridbusinessbuildershelsinkixn--4gbrimмоскваالسعودیةcoffeedegreelacaixapartnersalsaceofficeabbvievoyageorangegeorgeonlinechromemobilekindlegoogleoraclecircleschulesecureinsurexn--mgba7c0bbn0aestatexn--mgbc0a9azcgcruisehangoutxn--vuq861bxn--42c2d9arexrothfirestoneuniversityxn--nnx388alifeinsuranceextraspaceонлайнvermögensberatersoftwarexn--fiqs8sxn--mgbab2bdxn--w4rs40ltiendaभारतम्africatoyotaotsukasakuracameracreditcardnagoyaconsultingnetworkjunipertheatermonsterprogressivepioneerxn--55qw42gracingdatingvotingvikinglivinggivingxn--bck1b9a5dre4cbrotherweatherjoburgفلسطينlplfinancialxn--clchc0ea0b2g2a9gcdfutbolschoolsocialglobaldentalwoodsidechanelairtelmatteltravelrealtorwebcamstreamభారత్unicomalstomxn--nodexn--6frz82gmuseumfurniturexn--rvc1e0am3exn--mix891faccenturexn--11b4c3dismailineustardiscountquebeccomsecclinicservicesxn--y9a3aqxn--c1avgswatchchurchsearchالاردنmarketingcontacthealthmonashshoujisanofitaipeiamericanexpresssuzukiアマゾンクラウドポイントbhartiグーグルxn--mgberp4a5d4armemorialxn--1qqw23alondonmormoninstitutevisionbostonnortoncouponmaisonamazonvirginberlindesigndurbanolayannissananquanxihuanhitachikaufengardenreisenbayerntechnologydatsunxn--90a3aclatinocasinostudiophysioxn--ngbe9e0apharmacytattootaobaoaramcoexpertreportabbottdirectselectimamatfairwindspictettargetmarketintuittravelersinsurancecreditdupontryukyusuppliesxn--tckwebnpparibasschmidtmerckmsdyodobashirestaurantbridgestonecricketxn--fpcrj9c3dbostikbroadwayattorneylefrakemerckxn--fiq228c5hscareersfarmerswinnersflowersxn--wgbh1cguitarsxn--54b7fta0ccxn--p1acfmakeupgalluplandroverxn--kcrx77d1x4agoldpointbauhausxn--mgbayh7gpahiphopplaystationxn--mgba3a4fraxn--eckvdtc9dhyundaixn--gckr3f0fistanbulticketsmarketsflightschintaireviewsxn--3e0b707ewindowsxn--fiqz9sfinancialxn--fzys8d69uvgmابوظبيdiscoverreviewবাংলাxn--5su34j936bgsgmoscowobserverapartmentsдетиارامكوсайтeurovisionxn--i1b6b1a6a2exn--xkc2dl3a5ee0hتونسموقعبارتڀارتشبكةعمانبيتكعراقreadkredbondlandbandfundfoodprodgoldfordtubecafesafelifeggeeieeefreefagepagegugezonewinememenamegamesaleablebikenikelikecarecbreherefiresaveloveliveblueartedatesitevotecaseluxebofamodaltdaasdatiaayogasinavanashiaasiajavabbvatevavivadatazaraarpacasavisasncfprofmaifsurfgolfdvagsongbingpingwangkpmggoogblogpohlfailcooldellcalldeallidlsarlfilmteamroomfarmimdbarabclubhdfcicbchsbcgmbhrichtechfishdishcashminiernikddiaudiwikimobitaxicitikiwidesiqponskinloanakdnwienopenporncerntownimmolimoolloinfonicofidolegosaxozeroaerovivoautovotomotofastbestresthostpostnextlgbtchatseatgiftmeetdietreitmintrentgentspotscotguruitausohumenucyoubanklinkpinkdclktalksilkbookseekworkrsvpaarpjeepshopcoophelpcamppccwshowbeerstarruhrflirweirhaircarsparsjprshausplusnewstipstoysjobskidsfanspicsdocsxboxamexsexynavycitysonyarmyallybabyplaydeliverybuzzgbizlamborghiniphilipsලංකාಭಾರತfitnessexpresslanxesspfizercenterwalterlawyersoccercareerkosherbrokerlockerdealerdoctorauthorxn--mgbqly7c0a67fbcvermögensberatungjaguarxn--pssy2uxn--hxt814eflickrrepairrogersairbusxn--mgbai9a5eva00beventsyachtsxn--t60b56aভাৰতভারতभारतभारोतviajeshermeshughesxn--j1aefसंगठनvillasଭାରତclaimshotelsભારતzapposphotosjuegoscondostatamotorsgratistennisਭਾਰਤtkmaxxtjmaxxschaeffleryandexxn--80aswgrealtysafetybeautyluxuryxn--3ds443gsupplyfamilyxn--o3cw4hhockeysydneyxn--90aenissayalipayenergycomputeragencyxn--rovu88b電訊盈科xn--gecrj9cstatefarmaccountantaquarelleolayangroup香格里拉xn--p1ai组织机构xn--1ck2e1bxn--mgbt3dhdschwarzموريتانياabudhabinowruzkomatsufujitsuhospitalxn--80asehdbxn--mgbtf8flxn--j6w193gxn--yfro4i67oprudentialxn--flw351ecruisescoursesrecipesxn--e1a4cferrarixn--ses554gxn--wgbl6awatchesstaplessinglesxn--mgbcpq6gpa1axn--otu796dpropertiescreditunionxn--mgbah1a3hjkrdstockholmhisamitsuالسعوديةstcgroupdomainsoriginscouponsbloombergclubmedfroganslimitedxn--80aqecdr1aexposedinternationalequipmentbarclaycardxn--q7ce6axn--mgbi4ecexpprotectionassociatesconstructionxn--cck2b3bxn--45q11candroidfoundationישראלxn--mgbca7dzdocliniqueboutiqueengineerxn--qxa6asystemsfirmdalefashionauctionxn--nqv7finfinitirentalsreliancetradingweddingfishinghostinggentingbookingcookingxn--3hcrj9cgraingerxn--czrs0tdemocratsamsungyokohamaxn--h2breg3evexn--nyqy26alundbeckmelbournevacationssolutionsfrontierxn--vermgensberatung-pwbmanagementxn--cg4bkixn--mgb2ddeslincolnhamburgsandvikcoromantblockbusterairforcebarefootxn--4dbrk0ceinvestmentsfeedbackcommunityxn--ngbrxالبحرينdiamondsamsterdamhealthcareredumbrellaxn--mxtq1mxn--2scrj9cagakhanxn--mgbpl2fhкатоликcaravanசிங்கப்பூர்richardlimortgageamericanfamilyxn--fzc2c9e2cscholarshipssaarlandxn--imr513nvlaanderensamsclubgoodyearkitchenஇந்தியாweatherchannelallfinanzxn--kput3iالسعودیۃxn--90aisxn--efvy88hالجزائرxn--mgbaam7a8hexchangejpmorganxn--tiq49xqyjfidelitysecurityxn--mk1bu44cwanggouxn--fiq64bxn--6qq986b3xlxn--mgbbh1a71exn--80ao21amarshallsxn--5tzm5gtravelerspanasoniclatrobeyoutubeaccountantsxn--rhqv96gxn--cckwcxetdanalyticsxn--ygbi2ammxبازاربھارتسوريةorganicfreseniusسورياxn--9krt00axn--qcka1pmcxn--jlq480n2rgdeloittesciencefinancexn--jvr189mxn--30rr7yhomesensehotmailbaseballfootballleclercboehringerxn--q9jyb4cxn--mix082fاليمنهمراهpolitieسودانايرانایرانnetflixyamaxunxn--lgbbat1ad8jcollegestoragecapetowncolognekerrypropertiesxn--mgbgu82axn--ogbpf8flxn--czru2dwhoswhociprianilasallexn--g2xx48cforsalebanamexaudiblexn--vermgensberater-ctbxn--zfr164bericssonvanguardxn--45brj9cindustriestheatremarriottxn--3bst00mcomparexn--mgberp4a5d4a87gcapitaldigitalالمغربbarcelonashangrilaxn--d1alfcalvinkleinwwwcitysapporokawasakinagoyasendaikobekitakyushuyokohamackjp".charCodeAt(offset + i) !== hostname.charCodeAt(start + i)) return false;
		return true;
	}
	/**
	* Find the child edge of `node` whose label is `hostname[start, start + length)`.
	* Edges are sorted by hash, so binary-search the hash then verify the label
	* (scanning the rare run of equal hashes). Returns the edge index or -1.
	*/
	function findEdge(node, hash, hostname, start, length) {
		let lo = edgeStart[node];
		let hi = edgeStart[node + 1];
		while (lo < hi) {
			const mid = lo + hi >>> 1;
			const value = edgeHash[mid];
			if (value < hash) lo = mid + 1;
			else if (value > hash) hi = mid;
			else {
				for (let e = mid; e >= lo && edgeHash[e] === hash; e -= 1) if (labelEquals(e, hostname, start, length)) return e;
				for (let e = mid + 1; e < hi && edgeHash[e] === hash; e += 1) if (labelEquals(e, hostname, start, length)) return e;
				return -1;
			}
		}
		return -1;
	}
	/**
	* Walk `hostname`'s labels right-to-left from `root`, recording the deepest
	* node whose flag passes `allowedMask` (with the label boundaries of that match
	* in `matchStart`/`matchEnd`). Returns whether any match was found.
	*/
	function walk(hostname, root, allowedMask) {
		let node = root;
		let end = hostname.length;
		let hash = 5381;
		matchNode = -1;
		for (let i = hostname.length - 1; i >= 0; i -= 1) {
			const code = hostname.charCodeAt(i);
			if (code === 46) {
				const start = i + 1;
				let edge = findEdge(node, hash >>> 0, hostname, start, end - start);
				if (edge === -1) edge = wildcardEdge[node];
				if (edge === -1) return matchNode !== -1;
				node = edgeChild[edge];
				if ((nodeFlags[node] & allowedMask) !== 0) {
					matchNode = node;
					matchStart = start;
					matchEnd = end;
				}
				end = i;
				hash = 5381;
			} else hash = hash * 33 ^ code;
		}
		let edge = findEdge(node, hash >>> 0, hostname, 0, end);
		if (edge === -1) edge = wildcardEdge[node];
		if (edge !== -1) {
			node = edgeChild[edge];
			if ((nodeFlags[node] & allowedMask) !== 0) {
				matchNode = node;
				matchStart = 0;
				matchEnd = end;
			}
		}
		return matchNode !== -1;
	}
	/**
	* Check if `hostname` has a valid public suffix in the trie.
	*/
	function suffixLookup(hostname, options, out) {
		if (fast_path_default(hostname, options, out)) return;
		const allowedMask = (options.allowPrivateDomains ? 2 : 0) | (options.allowIcannDomains ? 1 : 0);
		if (walk(hostname, 628, allowedMask)) {
			out.isIcann = (nodeFlags[matchNode] & 1) !== 0;
			out.isPrivate = (nodeFlags[matchNode] & 2) !== 0;
			out.publicSuffix = hostname.slice(matchEnd + 1);
			return;
		}
		if (walk(hostname, 624, allowedMask)) {
			out.isIcann = (nodeFlags[matchNode] & 1) !== 0;
			out.isPrivate = (nodeFlags[matchNode] & 2) !== 0;
			out.publicSuffix = hostname.slice(matchStart);
			return;
		}
		out.isIcann = false;
		out.isPrivate = false;
		const lastDot = hostname.lastIndexOf(".");
		out.publicSuffix = lastDot === -1 ? hostname : hostname.slice(lastDot + 1);
	}
	//#endregion
	//#region node_modules/.pnpm/tldts@7.4.15/node_modules/tldts/dist/es6/index.js
	const RESULT = getEmptyResult();
	function getDomain(url, options) {
		resetResult(RESULT);
		return parseImpl$1(url, 3, suffixLookup, options, RESULT).domain;
	}
	//#endregion
	//#region node_modules/.pnpm/tough-cookie@6.0.2/node_modules/tough-cookie/dist/index.js
	function pathMatch(reqPath, cookiePath) {
		if (cookiePath === reqPath) return true;
		if (reqPath.indexOf(cookiePath) === 0) {
			if (cookiePath[cookiePath.length - 1] === "/") return true;
			if (reqPath.startsWith(cookiePath) && reqPath[cookiePath.length] === "/") return true;
		}
		return false;
	}
	var SPECIAL_USE_DOMAINS = [
		"local",
		"example",
		"invalid",
		"localhost",
		"test"
	];
	var SPECIAL_TREATMENT_DOMAINS = ["localhost", "invalid"];
	var defaultGetPublicSuffixOptions = {
		allowSpecialUseDomain: false,
		ignoreError: false
	};
	function getPublicSuffix(domain, options = {}) {
		options = {
			...defaultGetPublicSuffixOptions,
			...options
		};
		const domainParts = domain.split(".");
		const topLevelDomain = domainParts[domainParts.length - 1];
		const allowSpecialUseDomain = !!options.allowSpecialUseDomain;
		const ignoreError = !!options.ignoreError;
		if (allowSpecialUseDomain && topLevelDomain !== void 0 && SPECIAL_USE_DOMAINS.includes(topLevelDomain)) {
			if (domainParts.length > 1) return `${domainParts[domainParts.length - 2]}.${topLevelDomain}`;
			else if (SPECIAL_TREATMENT_DOMAINS.includes(topLevelDomain)) return topLevelDomain;
		}
		if (!ignoreError && topLevelDomain !== void 0 && SPECIAL_USE_DOMAINS.includes(topLevelDomain)) throw new Error(`Cookie has domain set to the public suffix "${topLevelDomain}" which is a special use domain. To allow this, configure your CookieJar with {allowSpecialUseDomain: true, rejectPublicSuffixes: false}.`);
		const publicSuffix = getDomain(domain, {
			allowIcannDomains: true,
			allowPrivateDomains: true
		});
		if (publicSuffix) return publicSuffix;
	}
	function permuteDomain(domain, allowSpecialUseDomain) {
		const pubSuf = getPublicSuffix(domain, { allowSpecialUseDomain });
		if (!pubSuf) return;
		if (pubSuf == domain) return [domain];
		if (domain.slice(-1) == ".") domain = domain.slice(0, -1);
		const parts = domain.slice(0, -(pubSuf.length + 1)).split(".").reverse();
		let cur = pubSuf;
		const permutations = [cur];
		while (parts.length) {
			cur = `${parts.shift()}.${cur}`;
			permutations.push(cur);
		}
		return permutations;
	}
	var Store = class {
		constructor() {
			this.synchronous = false;
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		findCookie(_domain, _path, _key, _callback) {
			throw new Error("findCookie is not implemented");
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		findCookies(_domain, _path, _allowSpecialUseDomain = false, _callback) {
			throw new Error("findCookies is not implemented");
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		putCookie(_cookie, _callback) {
			throw new Error("putCookie is not implemented");
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		updateCookie(_oldCookie, _newCookie, _callback) {
			throw new Error("updateCookie is not implemented");
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		removeCookie(_domain, _path, _key, _callback) {
			throw new Error("removeCookie is not implemented");
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		removeCookies(_domain, _path, _callback) {
			throw new Error("removeCookies is not implemented");
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		removeAllCookies(_callback) {
			throw new Error("removeAllCookies is not implemented");
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		getAllCookies(_callback) {
			throw new Error("getAllCookies is not implemented (therefore jar cannot be serialized)");
		}
	};
	var objectToString = (obj) => Object.prototype.toString.call(obj);
	var safeArrayToString = (arr, seenArrays) => {
		if (typeof arr.join !== "function") return objectToString(arr);
		seenArrays.add(arr);
		return arr.map((val) => val === null || val === void 0 || seenArrays.has(val) ? "" : safeToStringImpl(val, seenArrays)).join();
	};
	var safeToStringImpl = (val, seenArrays = /* @__PURE__ */ new WeakSet()) => {
		if (typeof val !== "object" || val === null) return String(val);
		else if (typeof val.toString === "function") return Array.isArray(val) ? safeArrayToString(val, seenArrays) : String(val);
		else return objectToString(val);
	};
	var safeToString = (val) => safeToStringImpl(val);
	function createPromiseCallback(cb) {
		let callback;
		let resolve;
		let reject;
		const promise = new Promise((_resolve, _reject) => {
			resolve = _resolve;
			reject = _reject;
		});
		if (typeof cb === "function") callback = (err, result) => {
			try {
				if (err) cb(err);
				else cb(null, result);
			} catch (e) {
				reject(e instanceof Error ? e : /* @__PURE__ */ new Error());
			}
		};
		else callback = (err, result) => {
			try {
				if (err) reject(err);
				else resolve(result);
			} catch (e) {
				reject(e instanceof Error ? e : /* @__PURE__ */ new Error());
			}
		};
		return {
			promise,
			callback,
			resolve: (value) => {
				callback(null, value);
				return promise;
			},
			reject: (error) => {
				callback(error);
				return promise;
			}
		};
	}
	function inOperator(k, o) {
		return k in o;
	}
	var MemoryCookieStore = class extends Store {
		/**
		* Create a new {@link MemoryCookieStore}.
		*/
		constructor() {
			super();
			this.synchronous = true;
			this.idx = /* @__PURE__ */ Object.create(null);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		findCookie(domain, path, key, callback) {
			const promiseCallback = createPromiseCallback(callback);
			if (domain == null || path == null || key == null) return promiseCallback.resolve(void 0);
			const result = this.idx[domain]?.[path]?.[key];
			return promiseCallback.resolve(result);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		findCookies(domain, path, allowSpecialUseDomain = false, callback) {
			if (typeof allowSpecialUseDomain === "function") {
				callback = allowSpecialUseDomain;
				allowSpecialUseDomain = true;
			}
			const results = [];
			const promiseCallback = createPromiseCallback(callback);
			if (!domain) return promiseCallback.resolve([]);
			let pathMatcher;
			if (!path) pathMatcher = function matchAll(domainIndex) {
				for (const curPath in domainIndex) {
					const pathIndex = domainIndex[curPath];
					for (const key in pathIndex) {
						const value = pathIndex[key];
						if (value) results.push(value);
					}
				}
			};
			else pathMatcher = function matchRFC(domainIndex) {
				for (const cookiePath in domainIndex) if (pathMatch(path, cookiePath)) {
					const pathIndex = domainIndex[cookiePath];
					for (const key in pathIndex) {
						const value = pathIndex[key];
						if (value) results.push(value);
					}
				}
			};
			const domains = permuteDomain(domain, allowSpecialUseDomain) || [domain];
			const idx = this.idx;
			domains.forEach((curDomain) => {
				const domainIndex = idx[curDomain];
				if (!domainIndex) return;
				pathMatcher(domainIndex);
			});
			return promiseCallback.resolve(results);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		putCookie(cookie, callback) {
			const promiseCallback = createPromiseCallback(callback);
			const { domain, path, key } = cookie;
			if (domain == null || path == null || key == null) return promiseCallback.resolve(void 0);
			const domainEntry = this.idx[domain] ?? /* @__PURE__ */ Object.create(null);
			this.idx[domain] = domainEntry;
			const pathEntry = domainEntry[path] ?? /* @__PURE__ */ Object.create(null);
			domainEntry[path] = pathEntry;
			pathEntry[key] = cookie;
			return promiseCallback.resolve(void 0);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		updateCookie(_oldCookie, newCookie, callback) {
			if (callback) this.putCookie(newCookie, callback);
			else return this.putCookie(newCookie);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		removeCookie(domain, path, key, callback) {
			const promiseCallback = createPromiseCallback(callback);
			delete this.idx[domain]?.[path]?.[key];
			return promiseCallback.resolve(void 0);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		removeCookies(domain, path, callback) {
			const promiseCallback = createPromiseCallback(callback);
			const domainEntry = this.idx[domain];
			if (domainEntry) {
				if (path) delete domainEntry[path];
				else delete this.idx[domain];
			}
			return promiseCallback.resolve(void 0);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		removeAllCookies(callback) {
			const promiseCallback = createPromiseCallback(callback);
			this.idx = /* @__PURE__ */ Object.create(null);
			return promiseCallback.resolve(void 0);
		}
		/**
		* @internal No doc because this is an overload that supports the implementation
		*/
		getAllCookies(callback) {
			const promiseCallback = createPromiseCallback(callback);
			const cookies = [];
			const idx = this.idx;
			Object.keys(idx).forEach((domain) => {
				const domainEntry = idx[domain] ?? {};
				Object.keys(domainEntry).forEach((path) => {
					const pathEntry = domainEntry[path] ?? {};
					Object.keys(pathEntry).forEach((key) => {
						const keyEntry = pathEntry[key];
						if (keyEntry != null) cookies.push(keyEntry);
					});
				});
			});
			cookies.sort((a, b) => {
				return (a.creationIndex || 0) - (b.creationIndex || 0);
			});
			return promiseCallback.resolve(cookies);
		}
	};
	function isNonEmptyString$1(data) {
		return isString(data) && data !== "";
	}
	function isEmptyString(data) {
		return data === "" || data instanceof String && data.toString() === "";
	}
	function isString(data) {
		return typeof data === "string" || data instanceof String;
	}
	function isObject$1(data) {
		return objectToString(data) === "[object Object]";
	}
	function validate(bool, cbOrMessage, message) {
		if (bool) return;
		const cb = typeof cbOrMessage === "function" ? cbOrMessage : void 0;
		let options = typeof cbOrMessage === "function" ? message : cbOrMessage;
		if (!isObject$1(options)) options = "[object Object]";
		const err = new ParameterError(safeToString(options));
		if (cb) cb(err);
		else throw err;
	}
	var ParameterError = class extends Error {};
	var version = "6.0.2";
	var PrefixSecurityEnum = {
		SILENT: "silent",
		STRICT: "strict",
		DISABLED: "unsafe-disabled"
	};
	Object.freeze(PrefixSecurityEnum);
	var IP_V6_REGEX = `
\\[?(?:
(?:[a-fA-F\\d]{1,4}:){7}(?:[a-fA-F\\d]{1,4}|:)|
(?:[a-fA-F\\d]{1,4}:){6}(?:(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)(?:\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)){3}|:[a-fA-F\\d]{1,4}|:)|
(?:[a-fA-F\\d]{1,4}:){5}(?::(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)(?:\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)){3}|(?::[a-fA-F\\d]{1,4}){1,2}|:)|
(?:[a-fA-F\\d]{1,4}:){4}(?:(?::[a-fA-F\\d]{1,4}){0,1}:(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)(?:\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)){3}|(?::[a-fA-F\\d]{1,4}){1,3}|:)|
(?:[a-fA-F\\d]{1,4}:){3}(?:(?::[a-fA-F\\d]{1,4}){0,2}:(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)(?:\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)){3}|(?::[a-fA-F\\d]{1,4}){1,4}|:)|
(?:[a-fA-F\\d]{1,4}:){2}(?:(?::[a-fA-F\\d]{1,4}){0,3}:(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)(?:\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)){3}|(?::[a-fA-F\\d]{1,4}){1,5}|:)|
(?:[a-fA-F\\d]{1,4}:){1}(?:(?::[a-fA-F\\d]{1,4}){0,4}:(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)(?:\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)){3}|(?::[a-fA-F\\d]{1,4}){1,6}|:)|
(?::(?:(?::[a-fA-F\\d]{1,4}){0,5}:(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)(?:\\.(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]\\d|\\d)){3}|(?::[a-fA-F\\d]{1,4}){1,7}|:))
)(?:%[0-9a-zA-Z]{1,})?\\]?
`.replace(/\s*\/\/.*$/gm, "").replace(/\n/g, "").trim();
	var IP_V6_REGEX_OBJECT = new RegExp(`^${IP_V6_REGEX}$`);
	var IP_V4_REGEX_OBJECT = new RegExp(`^(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])$`);
	function domainToASCII(domain) {
		return new URL(`http://${domain}`).hostname;
	}
	function canonicalDomain(domainName) {
		if (domainName == null) return;
		let str = domainName.trim().replace(/^\./, "");
		if (IP_V6_REGEX_OBJECT.test(str)) {
			if (!str.startsWith("[")) str = "[" + str;
			if (!str.endsWith("]")) str = str + "]";
			return domainToASCII(str).slice(1, -1);
		}
		if (/[^\u0001-\u007f]/.test(str)) return domainToASCII(str);
		return str.toLowerCase();
	}
	function formatDate(date) {
		return date.toUTCString();
	}
	function parseDate(cookieDate) {
		if (!cookieDate) return;
		const flags = {
			foundTime: void 0,
			foundDayOfMonth: void 0,
			foundMonth: void 0,
			foundYear: void 0
		};
		const dateTokens = cookieDate.split(DELIMITER).filter((token) => token.length > 0);
		for (const dateToken of dateTokens) {
			if (flags.foundTime === void 0) {
				const [, hours, minutes, seconds] = TIME.exec(dateToken) || [];
				if (hours != void 0 && minutes != void 0 && seconds != void 0) {
					const parsedHours = parseInt(hours, 10);
					const parsedMinutes = parseInt(minutes, 10);
					const parsedSeconds = parseInt(seconds, 10);
					if (!isNaN(parsedHours) && !isNaN(parsedMinutes) && !isNaN(parsedSeconds)) {
						flags.foundTime = {
							hours: parsedHours,
							minutes: parsedMinutes,
							seconds: parsedSeconds
						};
						continue;
					}
				}
			}
			if (flags.foundDayOfMonth === void 0 && DAY_OF_MONTH.test(dateToken)) {
				const dayOfMonth = parseInt(dateToken, 10);
				if (!isNaN(dayOfMonth)) {
					flags.foundDayOfMonth = dayOfMonth;
					continue;
				}
			}
			if (flags.foundMonth === void 0 && MONTH.test(dateToken)) {
				const month = months.indexOf(dateToken.substring(0, 3).toLowerCase());
				if (month >= 0 && month <= 11) {
					flags.foundMonth = month;
					continue;
				}
			}
			if (flags.foundYear === void 0 && YEAR.test(dateToken)) {
				const parsedYear = parseInt(dateToken, 10);
				if (!isNaN(parsedYear)) {
					flags.foundYear = parsedYear;
					continue;
				}
			}
		}
		if (flags.foundYear !== void 0 && flags.foundYear >= 70 && flags.foundYear <= 99) flags.foundYear += 1900;
		if (flags.foundYear !== void 0 && flags.foundYear >= 0 && flags.foundYear <= 69) flags.foundYear += 2e3;
		if (flags.foundDayOfMonth === void 0 || flags.foundMonth === void 0 || flags.foundYear === void 0 || flags.foundTime === void 0) return;
		if (flags.foundDayOfMonth < 1 || flags.foundDayOfMonth > 31) return;
		if (flags.foundYear < 1601) return;
		if (flags.foundTime.hours > 23) return;
		if (flags.foundTime.minutes > 59) return;
		if (flags.foundTime.seconds > 59) return;
		const date = new Date(Date.UTC(flags.foundYear, flags.foundMonth, flags.foundDayOfMonth, flags.foundTime.hours, flags.foundTime.minutes, flags.foundTime.seconds));
		if (date.getUTCFullYear() !== flags.foundYear || date.getUTCMonth() !== flags.foundMonth || date.getUTCDate() !== flags.foundDayOfMonth) return;
		return date;
	}
	var months = [
		"jan",
		"feb",
		"mar",
		"apr",
		"may",
		"jun",
		"jul",
		"aug",
		"sep",
		"oct",
		"nov",
		"dec"
	];
	var DELIMITER = /[\x09\x20-\x2F\x3B-\x40\x5B-\x60\x7B-\x7E]/;
	var TIME = /^(\d{1,2}):(\d{1,2}):(\d{1,2})(?:[\x00-\x2F\x3A-\xFF][\x00-\xFF]*)?$/;
	var DAY_OF_MONTH = /^[0-9]{1,2}(?:[\x00-\x2F\x3A-\xFF][\x00-\xFF]*)?$/;
	var MONTH = /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[\x00-\xFF]*$/i;
	var YEAR = /^[\x30-\x39]{2,4}(?:[\x00-\x2F\x3A-\xFF][\x00-\xFF]*)?$/;
	var COOKIE_OCTETS = /^[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]+$/;
	var PATH_VALUE = /[\x20-\x3A\x3C-\x7E]+/;
	var CONTROL_CHARS = /[\x00-\x1F]/;
	var TERMINATORS = [
		"\n",
		"\r",
		"\0"
	];
	function trimTerminator(str) {
		if (isEmptyString(str)) return str;
		for (let t = 0; t < TERMINATORS.length; t++) {
			const terminator = TERMINATORS[t];
			const terminatorIdx = terminator ? str.indexOf(terminator) : -1;
			if (terminatorIdx !== -1) str = str.slice(0, terminatorIdx);
		}
		return str;
	}
	function parseCookiePair(cookiePair, looseMode) {
		cookiePair = trimTerminator(cookiePair);
		let firstEq = cookiePair.indexOf("=");
		if (looseMode) {
			if (firstEq === 0) {
				cookiePair = cookiePair.substring(1);
				firstEq = cookiePair.indexOf("=");
			}
		} else if (firstEq <= 0) return;
		let cookieName, cookieValue;
		if (firstEq <= 0) {
			cookieName = "";
			cookieValue = cookiePair.trim();
		} else {
			cookieName = cookiePair.slice(0, firstEq).trim();
			cookieValue = cookiePair.slice(firstEq + 1).trim();
		}
		if (CONTROL_CHARS.test(cookieName) || CONTROL_CHARS.test(cookieValue)) return;
		const c = new Cookie();
		c.key = cookieName;
		c.value = cookieValue;
		return c;
	}
	function parse$1(str, options) {
		if (isEmptyString(str) || !isString(str)) return;
		str = str.trim();
		const firstSemi = str.indexOf(";");
		const c = parseCookiePair(firstSemi === -1 ? str : str.slice(0, firstSemi), options?.loose ?? false);
		if (!c) return;
		if (firstSemi === -1) return c;
		const unparsed = str.slice(firstSemi + 1).trim();
		if (unparsed.length === 0) return c;
		const cookie_avs = unparsed.split(";");
		while (cookie_avs.length) {
			const av = (cookie_avs.shift() ?? "").trim();
			if (av.length === 0) continue;
			const av_sep = av.indexOf("=");
			let av_key, av_value;
			if (av_sep === -1) {
				av_key = av;
				av_value = null;
			} else {
				av_key = av.slice(0, av_sep);
				av_value = av.slice(av_sep + 1);
			}
			av_key = av_key.trim().toLowerCase();
			if (av_value) av_value = av_value.trim();
			switch (av_key) {
				case "expires":
					if (av_value) {
						const exp = parseDate(av_value);
						if (exp) c.expires = exp;
					}
					break;
				case "max-age":
					if (av_value) {
						if (/^-?[0-9]+$/.test(av_value)) {
							const delta = parseInt(av_value, 10);
							c.setMaxAge(delta);
						}
					}
					break;
				case "domain":
					if (av_value) {
						const domain = av_value.trim().replace(/^\./, "");
						if (domain) c.domain = domain.toLowerCase();
					}
					break;
				case "path":
					c.path = av_value && av_value[0] === "/" ? av_value : null;
					break;
				case "secure":
					c.secure = true;
					break;
				case "httponly":
					c.httpOnly = true;
					break;
				case "samesite":
					switch (av_value ? av_value.toLowerCase() : "") {
						case "strict":
							c.sameSite = "strict";
							break;
						case "lax":
							c.sameSite = "lax";
							break;
						case "none":
							c.sameSite = "none";
							break;
						default: c.sameSite = void 0;
					}
					break;
				default:
					c.extensions = c.extensions || [];
					c.extensions.push(av);
			}
		}
		return c;
	}
	function fromJSON(str) {
		if (!str || isEmptyString(str)) return;
		let obj;
		if (typeof str === "string") try {
			obj = JSON.parse(str);
		} catch {
			return;
		}
		else obj = str;
		const c = new Cookie();
		Cookie.serializableProperties.forEach((prop) => {
			if (obj && typeof obj === "object" && inOperator(prop, obj)) {
				const val = obj[prop];
				if (val === void 0) return;
				if (inOperator(prop, cookieDefaults) && val === cookieDefaults[prop]) return;
				switch (prop) {
					case "key":
					case "value":
					case "sameSite":
						if (typeof val === "string") c[prop] = val;
						break;
					case "expires":
					case "creation":
					case "lastAccessed":
						if (typeof val === "number" || typeof val === "string" || val instanceof Date) c[prop] = obj[prop] == "Infinity" ? "Infinity" : new Date(val);
						else if (val === null) c[prop] = null;
						break;
					case "maxAge":
						if (typeof val === "number" || val === "Infinity" || val === "-Infinity") c[prop] = val;
						break;
					case "domain":
					case "path":
						if (typeof val === "string" || val === null) c[prop] = val;
						break;
					case "secure":
					case "httpOnly":
						if (typeof val === "boolean") c[prop] = val;
						break;
					case "extensions":
						if (Array.isArray(val) && val.every((item) => typeof item === "string")) c[prop] = val;
						break;
					case "hostOnly":
					case "pathIsDefault": if (typeof val === "boolean" || val === null) c[prop] = val;
				}
			}
		});
		return c;
	}
	var cookieDefaults = {
		key: "",
		value: "",
		expires: "Infinity",
		maxAge: null,
		domain: null,
		path: null,
		secure: false,
		httpOnly: false,
		extensions: null,
		hostOnly: null,
		pathIsDefault: null,
		creation: null,
		lastAccessed: null,
		sameSite: void 0
	};
	var _Cookie = class _Cookie {
		/**
		* Create a new Cookie instance.
		* @public
		* @param options - The attributes to set on the cookie
		*/
		constructor(options = {}) {
			this.key = options.key ?? cookieDefaults.key;
			this.value = options.value ?? cookieDefaults.value;
			this.expires = options.expires ?? cookieDefaults.expires;
			this.maxAge = options.maxAge ?? cookieDefaults.maxAge;
			this.domain = options.domain ?? cookieDefaults.domain;
			this.path = options.path ?? cookieDefaults.path;
			this.secure = options.secure ?? cookieDefaults.secure;
			this.httpOnly = options.httpOnly ?? cookieDefaults.httpOnly;
			this.extensions = options.extensions ?? cookieDefaults.extensions;
			this.creation = options.creation ?? cookieDefaults.creation;
			this.hostOnly = options.hostOnly ?? cookieDefaults.hostOnly;
			this.pathIsDefault = options.pathIsDefault ?? cookieDefaults.pathIsDefault;
			this.lastAccessed = options.lastAccessed ?? cookieDefaults.lastAccessed;
			this.sameSite = options.sameSite ?? cookieDefaults.sameSite;
			this.creation = options.creation ?? /* @__PURE__ */ new Date();
			Object.defineProperty(this, "creationIndex", {
				configurable: false,
				enumerable: false,
				writable: true,
				value: ++_Cookie.cookiesCreated
			});
			this.creationIndex = _Cookie.cookiesCreated;
		}
		[/* @__PURE__ */ Symbol.for("nodejs.util.inspect.custom")]() {
			const now = Date.now();
			const hostOnly = this.hostOnly != null ? this.hostOnly.toString() : "?";
			const createAge = this.creation && this.creation !== "Infinity" ? `${String(now - this.creation.getTime())}ms` : "?";
			const accessAge = this.lastAccessed && this.lastAccessed !== "Infinity" ? `${String(now - this.lastAccessed.getTime())}ms` : "?";
			return `Cookie="${this.toString()}; hostOnly=${hostOnly}; aAge=${accessAge}; cAge=${createAge}"`;
		}
		/**
		* For convenience in using `JSON.stringify(cookie)`. Returns a plain-old Object that can be JSON-serialized.
		*
		* @remarks
		* - Any `Date` properties (such as {@link Cookie.expires}, {@link Cookie.creation}, and {@link Cookie.lastAccessed}) are exported in ISO format (`Date.toISOString()`).
		*
		*  - Custom Cookie properties are discarded. In tough-cookie 1.x, since there was no {@link Cookie.toJSON} method explicitly defined, all enumerable properties were captured.
		*      If you want a property to be serialized, add the property name to {@link Cookie.serializableProperties}.
		*/
		toJSON() {
			const obj = {};
			for (const prop of _Cookie.serializableProperties) {
				const val = this[prop];
				if (val === cookieDefaults[prop]) continue;
				switch (prop) {
					case "key":
					case "value":
					case "sameSite":
						if (typeof val === "string") obj[prop] = val;
						break;
					case "expires":
					case "creation":
					case "lastAccessed":
						if (typeof val === "number" || typeof val === "string" || val instanceof Date) obj[prop] = val == "Infinity" ? "Infinity" : new Date(val).toISOString();
						else if (val === null) obj[prop] = null;
						break;
					case "maxAge":
						if (typeof val === "number" || val === "Infinity" || val === "-Infinity") obj[prop] = val;
						break;
					case "domain":
					case "path":
						if (typeof val === "string" || val === null) obj[prop] = val;
						break;
					case "secure":
					case "httpOnly":
						if (typeof val === "boolean") obj[prop] = val;
						break;
					case "extensions":
						if (Array.isArray(val)) obj[prop] = val;
						break;
					case "hostOnly":
					case "pathIsDefault": if (typeof val === "boolean" || val === null) obj[prop] = val;
				}
			}
			return obj;
		}
		/**
		* Does a deep clone of this cookie, implemented exactly as `Cookie.fromJSON(cookie.toJSON())`.
		* @public
		*/
		clone() {
			return fromJSON(this.toJSON());
		}
		/**
		* Validates cookie attributes for semantic correctness. Useful for "lint" checking any `Set-Cookie` headers you generate.
		* For now, it returns a boolean, but eventually could return a reason string.
		*
		* @remarks
		* Works for a few things, but is by no means comprehensive.
		*
		* @beta
		*/
		validate() {
			if (!this.value || !COOKIE_OCTETS.test(this.value)) return false;
			if (this.expires != "Infinity" && !(this.expires instanceof Date) && !parseDate(this.expires)) return false;
			if (this.maxAge != null && this.maxAge !== "Infinity" && (this.maxAge === "-Infinity" || this.maxAge <= 0)) return false;
			if (this.path != null && !PATH_VALUE.test(this.path)) return false;
			const cdomain = this.cdomain();
			if (cdomain) {
				if (cdomain.match(/\.$/)) return false;
				if (getPublicSuffix(cdomain) == null) return false;
			}
			return true;
		}
		/**
		* Sets the 'Expires' attribute on a cookie.
		*
		* @remarks
		* When given a `string` value it will be parsed with {@link parseDate}. If the value can't be parsed as a cookie date
		* then the 'Expires' attribute will be set to `"Infinity"`.
		*
		* @param exp - the new value for the 'Expires' attribute of the cookie.
		*/
		setExpires(exp) {
			if (exp instanceof Date) this.expires = exp;
			else this.expires = parseDate(exp) || "Infinity";
		}
		/**
		* Sets the 'Max-Age' attribute (in seconds) on a cookie.
		*
		* @remarks
		* Coerces `-Infinity` to `"-Infinity"` and `Infinity` to `"Infinity"` so it can be serialized to JSON.
		*
		* @param age - the new value for the 'Max-Age' attribute (in seconds).
		*/
		setMaxAge(age) {
			if (age === Infinity) this.maxAge = "Infinity";
			else if (age === -Infinity) this.maxAge = "-Infinity";
			else this.maxAge = age;
		}
		/**
		* Encodes to a `Cookie` header value (specifically, the {@link Cookie.key} and {@link Cookie.value} properties joined with "=").
		* @public
		*/
		cookieString() {
			const val = this.value || "";
			if (this.key) return `${this.key}=${val}`;
			return val;
		}
		/**
		* Encodes to a `Set-Cookie header` value.
		* @public
		*/
		toString() {
			let str = this.cookieString();
			if (this.expires != "Infinity") {
				if (this.expires instanceof Date) str += `; Expires=${formatDate(this.expires)}`;
			}
			if (this.maxAge != null && this.maxAge != Infinity) str += `; Max-Age=${String(this.maxAge)}`;
			if (this.domain && !this.hostOnly) str += `; Domain=${this.domain}`;
			if (this.path) str += `; Path=${this.path}`;
			if (this.secure) str += "; Secure";
			if (this.httpOnly) str += "; HttpOnly";
			if (this.sameSite && this.sameSite !== "none") {
				if (this.sameSite.toLowerCase() === _Cookie.sameSiteCanonical.lax.toLowerCase()) str += `; SameSite=${_Cookie.sameSiteCanonical.lax}`;
				else if (this.sameSite.toLowerCase() === _Cookie.sameSiteCanonical.strict.toLowerCase()) str += `; SameSite=${_Cookie.sameSiteCanonical.strict}`;
				else str += `; SameSite=${this.sameSite}`;
			}
			if (this.extensions) this.extensions.forEach((ext) => {
				str += `; ${ext}`;
			});
			return str;
		}
		/**
		* Computes the TTL relative to now (milliseconds).
		*
		* @remarks
		* - `Infinity` is returned for cookies without an explicit expiry
		*
		* - `0` is returned if the cookie is expired.
		*
		* - Otherwise a time-to-live in milliseconds is returned.
		*
		* @param now - passing an explicit value is mostly used for testing purposes since this defaults to the `Date.now()`
		* @public
		*/
		TTL(now = Date.now()) {
			if (this.maxAge != null && typeof this.maxAge === "number") return this.maxAge <= 0 ? 0 : this.maxAge * 1e3;
			const expires = this.expires;
			if (expires === "Infinity") return Infinity;
			return (expires?.getTime() ?? now) - (now || Date.now());
		}
		/**
		* Computes the absolute unix-epoch milliseconds that this cookie expires.
		*
		* The "Max-Age" attribute takes precedence over "Expires" (as per the RFC). The {@link Cookie.lastAccessed} attribute
		* (or the `now` parameter if given) is used to offset the {@link Cookie.maxAge} attribute.
		*
		* If Expires ({@link Cookie.expires}) is set, that's returned.
		*
		* @param now - can be used to provide a time offset (instead of {@link Cookie.lastAccessed}) to use when calculating the "Max-Age" value
		*/
		expiryTime(now) {
			if (this.maxAge != null) {
				const relativeTo = now || this.lastAccessed || /* @__PURE__ */ new Date();
				const maxAge = typeof this.maxAge === "number" ? this.maxAge : -Infinity;
				const age = maxAge <= 0 ? -Infinity : maxAge * 1e3;
				if (relativeTo === "Infinity") return Infinity;
				return relativeTo.getTime() + age;
			}
			if (this.expires == "Infinity") return Infinity;
			return this.expires ? this.expires.getTime() : void 0;
		}
		/**
		* Similar to {@link Cookie.expiryTime}, computes the absolute unix-epoch milliseconds that this cookie expires and returns it as a Date.
		*
		* The "Max-Age" attribute takes precedence over "Expires" (as per the RFC). The {@link Cookie.lastAccessed} attribute
		* (or the `now` parameter if given) is used to offset the {@link Cookie.maxAge} attribute.
		*
		* If Expires ({@link Cookie.expires}) is set, that's returned.
		*
		* @param now - can be used to provide a time offset (instead of {@link Cookie.lastAccessed}) to use when calculating the "Max-Age" value
		*/
		expiryDate(now) {
			const millisec = this.expiryTime(now);
			if (millisec == Infinity) return /* @__PURE__ */ new Date(2147483647e3);
			else if (millisec == -Infinity) return /* @__PURE__ */ new Date(0);
			else return millisec == void 0 ? void 0 : new Date(millisec);
		}
		/**
		* Indicates if the cookie has been persisted to a store or not.
		* @public
		*/
		isPersistent() {
			return this.maxAge != null || this.expires != "Infinity";
		}
		/**
		* Calls {@link canonicalDomain} with the {@link Cookie.domain} property.
		* @public
		*/
		canonicalizedDomain() {
			return canonicalDomain(this.domain);
		}
		/**
		* Alias for {@link Cookie.canonicalizedDomain}
		* @public
		*/
		cdomain() {
			return canonicalDomain(this.domain);
		}
		/**
		* Parses a string into a Cookie object.
		*
		* @remarks
		* Note: when parsing a `Cookie` header it must be split by ';' before each Cookie string can be parsed.
		*
		* @example
		* ```
		* // parse a `Set-Cookie` header
		* const setCookieHeader = 'a=bcd; Expires=Tue, 18 Oct 2011 07:05:03 GMT'
		* const cookie = Cookie.parse(setCookieHeader)
		* cookie.key === 'a'
		* cookie.value === 'bcd'
		* cookie.expires === new Date(Date.parse('Tue, 18 Oct 2011 07:05:03 GMT'))
		* ```
		*
		* @example
		* ```
		* // parse a `Cookie` header
		* const cookieHeader = 'name=value; name2=value2; name3=value3'
		* const cookies = cookieHeader.split(';').map(Cookie.parse)
		* cookies[0].name === 'name'
		* cookies[0].value === 'value'
		* cookies[1].name === 'name2'
		* cookies[1].value === 'value2'
		* cookies[2].name === 'name3'
		* cookies[2].value === 'value3'
		* ```
		*
		* @param str - The `Set-Cookie` header or a Cookie string to parse.
		* @param options - Configures `strict` or `loose` mode for cookie parsing
		*/
		static parse(str, options) {
			return parse$1(str, options);
		}
		/**
		* Does the reverse of {@link Cookie.toJSON}.
		*
		* @remarks
		* Any Date properties (such as .expires, .creation, and .lastAccessed) are parsed via Date.parse, not tough-cookie's parseDate, since ISO timestamps are being handled at this layer.
		*
		* @example
		* ```
		* const json = JSON.stringify({
		*   key: 'alpha',
		*   value: 'beta',
		*   domain: 'example.com',
		*   path: '/foo',
		*   expires: '2038-01-19T03:14:07.000Z',
		* })
		* const cookie = Cookie.fromJSON(json)
		* cookie.key === 'alpha'
		* cookie.value === 'beta'
		* cookie.domain === 'example.com'
		* cookie.path === '/foo'
		* cookie.expires === new Date(Date.parse('2038-01-19T03:14:07.000Z'))
		* ```
		*
		* @param str - An unparsed JSON string or a value that has already been parsed as JSON
		*/
		static fromJSON(str) {
			return fromJSON(str);
		}
	};
	_Cookie.cookiesCreated = 0;
	/**
	* @internal
	*/
	_Cookie.sameSiteLevel = {
		strict: 3,
		lax: 2,
		none: 1
	};
	/**
	* @internal
	*/
	_Cookie.sameSiteCanonical = {
		strict: "Strict",
		lax: "Lax"
	};
	/**
	* Cookie properties that will be serialized when using {@link Cookie.fromJSON} and {@link Cookie.toJSON}.
	* @public
	*/
	_Cookie.serializableProperties = [
		"key",
		"value",
		"expires",
		"maxAge",
		"domain",
		"path",
		"secure",
		"httpOnly",
		"extensions",
		"hostOnly",
		"pathIsDefault",
		"creation",
		"lastAccessed",
		"sameSite"
	];
	var Cookie = _Cookie;
	var MAX_TIME = 2147483647e3;
	function cookieCompare(a, b) {
		let cmp;
		const aPathLen = a.path ? a.path.length : 0;
		cmp = (b.path ? b.path.length : 0) - aPathLen;
		if (cmp !== 0) return cmp;
		cmp = (a.creation && a.creation instanceof Date ? a.creation.getTime() : MAX_TIME) - (b.creation && b.creation instanceof Date ? b.creation.getTime() : MAX_TIME);
		if (cmp !== 0) return cmp;
		cmp = (a.creationIndex || 0) - (b.creationIndex || 0);
		return cmp;
	}
	function defaultPath(path) {
		if (!path || path.slice(0, 1) !== "/") return "/";
		if (path === "/") return path;
		const rightSlash = path.lastIndexOf("/");
		if (rightSlash === 0) return "/";
		return path.slice(0, rightSlash);
	}
	var IP_REGEX_LOWERCASE = /(?:^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}$)|(?:^(?:(?:[a-f\d]{1,4}:){7}(?:[a-f\d]{1,4}|:)|(?:[a-f\d]{1,4}:){6}(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}|:[a-f\d]{1,4}|:)|(?:[a-f\d]{1,4}:){5}(?::(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}|(?::[a-f\d]{1,4}){1,2}|:)|(?:[a-f\d]{1,4}:){4}(?:(?::[a-f\d]{1,4}){0,1}:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}|(?::[a-f\d]{1,4}){1,3}|:)|(?:[a-f\d]{1,4}:){3}(?:(?::[a-f\d]{1,4}){0,2}:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}|(?::[a-f\d]{1,4}){1,4}|:)|(?:[a-f\d]{1,4}:){2}(?:(?::[a-f\d]{1,4}){0,3}:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}|(?::[a-f\d]{1,4}){1,5}|:)|(?:[a-f\d]{1,4}:){1}(?:(?::[a-f\d]{1,4}){0,4}:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}|(?::[a-f\d]{1,4}){1,6}|:)|(?::(?:(?::[a-f\d]{1,4}){0,5}:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]\d|\d)){3}|(?::[a-f\d]{1,4}){1,7}|:)))$)/;
	function domainMatch(domain, cookieDomain, canonicalize) {
		if (domain == null || cookieDomain == null) return;
		let _str;
		let _domStr;
		if (canonicalize !== false) {
			_str = canonicalDomain(domain);
			_domStr = canonicalDomain(cookieDomain);
		} else {
			_str = domain;
			_domStr = cookieDomain;
		}
		if (_str == null || _domStr == null) return;
		if (_str == _domStr) return true;
		const idx = _str.lastIndexOf(_domStr);
		if (idx <= 0) return false;
		if (_str.length !== _domStr.length + idx) return false;
		if (_str.substring(idx - 1, idx) !== ".") return false;
		return !IP_REGEX_LOWERCASE.test(_str);
	}
	function isLoopbackV4(address) {
		const octets = address.split(".");
		return octets.length === 4 && octets[0] !== void 0 && parseInt(octets[0], 10) === 127;
	}
	function isLoopbackV6(address) {
		return address === "::1";
	}
	function isNormalizedLocalhostTLD(lowerHost) {
		return lowerHost.endsWith(".localhost");
	}
	function isLocalHostname(host) {
		const lowerHost = host.toLowerCase();
		return lowerHost === "localhost" || isNormalizedLocalhostTLD(lowerHost);
	}
	function hostNoBrackets(host) {
		if (host.length >= 2 && host.startsWith("[") && host.endsWith("]")) return host.substring(1, host.length - 1);
		return host;
	}
	function isPotentiallyTrustworthy(inputUrl, allowSecureOnLocal = true) {
		let url;
		if (typeof inputUrl === "string") try {
			url = new URL(inputUrl);
		} catch {
			return false;
		}
		else url = inputUrl;
		const scheme = url.protocol.replace(":", "").toLowerCase();
		const hostname = hostNoBrackets(url.hostname).replace(/\.+$/, "");
		if (scheme === "https" || scheme === "wss") return true;
		if (!allowSecureOnLocal) return false;
		if (IP_V4_REGEX_OBJECT.test(hostname)) return isLoopbackV4(hostname);
		if (IP_V6_REGEX_OBJECT.test(hostname)) return isLoopbackV6(hostname);
		return isLocalHostname(hostname);
	}
	var defaultSetCookieOptions = {
		loose: false,
		sameSiteContext: void 0,
		ignoreError: false,
		http: true
	};
	var defaultGetCookieOptions = {
		http: true,
		expire: true,
		allPaths: false,
		sameSiteContext: void 0,
		sort: void 0
	};
	var SAME_SITE_CONTEXT_VAL_ERR = "Invalid sameSiteContext option for getCookies(); expected one of \"strict\", \"lax\", or \"none\"";
	function getCookieContext(url) {
		if (url && typeof url === "object" && "hostname" in url && typeof url.hostname === "string" && "pathname" in url && typeof url.pathname === "string" && "protocol" in url && typeof url.protocol === "string") return {
			hostname: url.hostname,
			pathname: url.pathname,
			protocol: url.protocol
		};
		else if (typeof url === "string") {
			const parsed = new URL(url);
			let pathname = parsed.pathname;
			try {
				pathname = decodeURI(pathname);
			} catch {}
			return {
				hostname: parsed.hostname,
				pathname,
				protocol: parsed.protocol
			};
		} else throw new ParameterError("`url` argument is not a string or URL.");
	}
	function checkSameSiteContext(value) {
		const context = value.toLowerCase();
		if (context === "none" || context === "lax" || context === "strict") return context;
		else return;
	}
	function isSecurePrefixConditionMet(cookie) {
		return !(typeof cookie.key === "string" && cookie.key.startsWith("__Secure-")) || cookie.secure;
	}
	function isHostPrefixConditionMet(cookie) {
		return !(typeof cookie.key === "string" && cookie.key.startsWith("__Host-")) || Boolean(cookie.secure && cookie.hostOnly && cookie.path != null && cookie.path === "/");
	}
	function getNormalizedPrefixSecurity(prefixSecurity) {
		const normalizedPrefixSecurity = prefixSecurity.toLowerCase();
		switch (normalizedPrefixSecurity) {
			case PrefixSecurityEnum.STRICT:
			case PrefixSecurityEnum.SILENT:
			case PrefixSecurityEnum.DISABLED: return normalizedPrefixSecurity;
			default: return PrefixSecurityEnum.SILENT;
		}
	}
	var CookieJar = class _CookieJar {
		/**
		* Creates a new `CookieJar` instance.
		*
		* @remarks
		* - If a custom store is not passed to the constructor, an in-memory store ({@link MemoryCookieStore} will be created and used.
		* - If a boolean value is passed as the `options` parameter, this is equivalent to passing `{ rejectPublicSuffixes: <value> }`
		*
		* @param store - a custom {@link Store} implementation (defaults to {@link MemoryCookieStore})
		* @param options - configures how cookies are processed by the cookie jar
		*/
		constructor(store, options) {
			if (typeof options === "boolean") options = { rejectPublicSuffixes: options };
			this.rejectPublicSuffixes = options?.rejectPublicSuffixes ?? true;
			this.enableLooseMode = options?.looseMode ?? false;
			this.allowSpecialUseDomain = options?.allowSpecialUseDomain ?? true;
			this.allowSecureOnLocal = options?.allowSecureOnLocal ?? true;
			this.prefixSecurity = getNormalizedPrefixSecurity(options?.prefixSecurity ?? "silent");
			this.store = store ?? new MemoryCookieStore();
		}
		callSync(fn) {
			if (!this.store.synchronous) throw new Error("CookieJar store is not synchronous; use async API instead.");
			let syncErr = null;
			let syncResult = void 0;
			try {
				fn.call(this, (error, result) => {
					syncErr = error;
					syncResult = result;
				});
			} catch (err) {
				syncErr = err;
			}
			if (syncErr) throw syncErr;
			return syncResult;
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		setCookie(cookie, url, options, callback) {
			if (typeof options === "function") {
				callback = options;
				options = void 0;
			}
			const promiseCallback = createPromiseCallback(callback);
			const cb = promiseCallback.callback;
			let context;
			try {
				if (typeof url === "string") validate(isNonEmptyString$1(url), callback, safeToString(options));
				context = getCookieContext(url);
				if (typeof url === "function") return promiseCallback.reject(/* @__PURE__ */ new Error("No URL was specified"));
				if (typeof options === "function") options = defaultSetCookieOptions;
				validate(typeof cb === "function", cb);
				if (!isNonEmptyString$1(cookie) && !isObject$1(cookie) && cookie instanceof String && cookie.length == 0) return promiseCallback.resolve(void 0);
			} catch (err) {
				return promiseCallback.reject(err);
			}
			const host = canonicalDomain(context.hostname) ?? null;
			const loose = options?.loose || this.enableLooseMode;
			let sameSiteContext = null;
			if (options?.sameSiteContext) {
				sameSiteContext = checkSameSiteContext(options.sameSiteContext);
				if (!sameSiteContext) return promiseCallback.reject(new Error(SAME_SITE_CONTEXT_VAL_ERR));
			}
			if (typeof cookie === "string" || cookie instanceof String) {
				const parsedCookie = Cookie.parse(cookie.toString(), { loose });
				if (!parsedCookie) {
					const err = /* @__PURE__ */ new Error("Cookie failed to parse");
					return options?.ignoreError ? promiseCallback.resolve(void 0) : promiseCallback.reject(err);
				}
				cookie = parsedCookie;
			} else if (!(cookie instanceof Cookie)) {
				const err = /* @__PURE__ */ new Error("First argument to setCookie must be a Cookie object or string");
				return options?.ignoreError ? promiseCallback.resolve(void 0) : promiseCallback.reject(err);
			}
			const now = options?.now || /* @__PURE__ */ new Date();
			if (this.rejectPublicSuffixes && cookie.domain) try {
				const cdomain = cookie.cdomain();
				if ((typeof cdomain === "string" ? getPublicSuffix(cdomain, {
					allowSpecialUseDomain: this.allowSpecialUseDomain,
					ignoreError: options?.ignoreError
				}) : null) == null && !IP_V6_REGEX_OBJECT.test(cookie.domain)) {
					const err = /* @__PURE__ */ new Error("Cookie has domain set to a public suffix");
					return options?.ignoreError ? promiseCallback.resolve(void 0) : promiseCallback.reject(err);
				}
			} catch (err) {
				return options?.ignoreError ? promiseCallback.resolve(void 0) : promiseCallback.reject(err);
			}
			if (cookie.domain) {
				if (!domainMatch(host ?? void 0, cookie.cdomain() ?? void 0, false)) {
					const err = /* @__PURE__ */ new Error(`Cookie not in this host's domain. Cookie:${cookie.cdomain() ?? "null"} Request:${host ?? "null"}`);
					return options?.ignoreError ? promiseCallback.resolve(void 0) : promiseCallback.reject(err);
				}
				if (cookie.hostOnly == null) cookie.hostOnly = false;
			} else {
				cookie.hostOnly = true;
				cookie.domain = host;
			}
			if (!cookie.path || cookie.path[0] !== "/") {
				cookie.path = defaultPath(context.pathname);
				cookie.pathIsDefault = true;
			}
			if (options?.http === false && cookie.httpOnly) {
				const err = /* @__PURE__ */ new Error("Cookie is HttpOnly and this isn't an HTTP API");
				return options.ignoreError ? promiseCallback.resolve(void 0) : promiseCallback.reject(err);
			}
			if (cookie.sameSite !== "none" && cookie.sameSite !== void 0 && sameSiteContext) {
				if (sameSiteContext === "none") {
					const err = /* @__PURE__ */ new Error("Cookie is SameSite but this is a cross-origin request");
					return options?.ignoreError ? promiseCallback.resolve(void 0) : promiseCallback.reject(err);
				}
			}
			const ignoreErrorForPrefixSecurity = this.prefixSecurity === PrefixSecurityEnum.SILENT;
			if (!(this.prefixSecurity === PrefixSecurityEnum.DISABLED)) {
				let errorFound = false;
				let errorMsg;
				if (!isSecurePrefixConditionMet(cookie)) {
					errorFound = true;
					errorMsg = "Cookie has __Secure prefix but Secure attribute is not set";
				} else if (!isHostPrefixConditionMet(cookie)) {
					errorFound = true;
					errorMsg = "Cookie has __Host prefix but either Secure or HostOnly attribute is not set or Path is not '/'";
				}
				if (errorFound) return options?.ignoreError || ignoreErrorForPrefixSecurity ? promiseCallback.resolve(void 0) : promiseCallback.reject(new Error(errorMsg));
			}
			const store = this.store;
			if (!store.updateCookie) store.updateCookie = async function(_oldCookie, newCookie, cb2) {
				return this.putCookie(newCookie).then(() => cb2?.(null), (error) => cb2?.(error));
			};
			store.findCookie(cookie.domain, cookie.path, cookie.key, function withCookie2(err, oldCookie) {
				if (err) {
					cb(err);
					return;
				}
				const next = function(err2) {
					if (err2) cb(err2);
					else if (typeof cookie === "string") cb(null, void 0);
					else cb(null, cookie);
				};
				if (oldCookie) {
					if (options && "http" in options && options.http === false && oldCookie.httpOnly) {
						err = /* @__PURE__ */ new Error("old Cookie is HttpOnly and this isn't an HTTP API");
						if (options.ignoreError) cb(null, void 0);
						else cb(err);
						return;
					}
					if (cookie instanceof Cookie) {
						cookie.creation = oldCookie.creation;
						cookie.creationIndex = oldCookie.creationIndex;
						cookie.lastAccessed = now;
						store.updateCookie(oldCookie, cookie, next);
					}
				} else if (cookie instanceof Cookie) {
					cookie.creation = cookie.lastAccessed = now;
					store.putCookie(cookie, next);
				}
			});
			return promiseCallback.promise;
		}
		/**
		* Synchronously attempt to set the {@link Cookie} in the {@link CookieJar}.
		*
		* <strong>Note:</strong> Only works if the configured {@link Store} is also synchronous.
		*
		* @remarks
		* - If successfully persisted, the {@link Cookie} will have updated
		*     {@link Cookie.creation}, {@link Cookie.lastAccessed} and {@link Cookie.hostOnly}
		*     properties.
		*
		* - As per the RFC, the {@link Cookie.hostOnly} flag is set if there was no `Domain={value}`
		*     attribute on the cookie string. The {@link Cookie.domain} property is set to the
		*     fully-qualified hostname of `currentUrl` in this case. Matching this cookie requires an
		*     exact hostname match (not a {@link domainMatch} as per usual)
		*
		* @param cookie - The cookie object or cookie string to store. A string value will be parsed into a cookie using {@link Cookie.parse}.
		* @param url - The domain to store the cookie with.
		* @param options - Configuration settings to use when storing the cookie.
		* @public
		*/
		setCookieSync(cookie, url, options) {
			const setCookieFn = options ? this.setCookie.bind(this, cookie, url, options) : this.setCookie.bind(this, cookie, url);
			return this.callSync(setCookieFn);
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		getCookies(url, options, callback) {
			if (typeof options === "function") {
				callback = options;
				options = defaultGetCookieOptions;
			} else if (options === void 0) options = defaultGetCookieOptions;
			const promiseCallback = createPromiseCallback(callback);
			const cb = promiseCallback.callback;
			let context;
			try {
				if (typeof url === "string") validate(isNonEmptyString$1(url), cb, url);
				context = getCookieContext(url);
				validate(isObject$1(options), cb, safeToString(options));
				validate(typeof cb === "function", cb);
			} catch (parameterError) {
				return promiseCallback.reject(parameterError);
			}
			const host = canonicalDomain(context.hostname);
			const path = context.pathname || "/";
			const potentiallyTrustworthy = isPotentiallyTrustworthy(url, this.allowSecureOnLocal);
			let sameSiteLevel = 0;
			if (options.sameSiteContext) {
				const sameSiteContext = checkSameSiteContext(options.sameSiteContext);
				if (sameSiteContext == null) return promiseCallback.reject(new Error(SAME_SITE_CONTEXT_VAL_ERR));
				sameSiteLevel = Cookie.sameSiteLevel[sameSiteContext];
				if (!sameSiteLevel) return promiseCallback.reject(new Error(SAME_SITE_CONTEXT_VAL_ERR));
			}
			const http = options.http ?? true;
			const now = Date.now();
			const expireCheck = options.expire ?? true;
			const allPaths = options.allPaths ?? false;
			const store = this.store;
			function matchingCookie(c) {
				if (c.hostOnly) {
					if (c.domain != host) return false;
				} else if (!domainMatch(host ?? void 0, c.domain ?? void 0, false)) return false;
				if (!allPaths && typeof c.path === "string" && !pathMatch(path, c.path)) return false;
				if (c.secure && !potentiallyTrustworthy) return false;
				if (c.httpOnly && !http) return false;
				if (sameSiteLevel) {
					let cookieLevel;
					if (c.sameSite === "lax") cookieLevel = Cookie.sameSiteLevel.lax;
					else if (c.sameSite === "strict") cookieLevel = Cookie.sameSiteLevel.strict;
					else cookieLevel = Cookie.sameSiteLevel.none;
					if (cookieLevel > sameSiteLevel) return false;
				}
				const expiryTime = c.expiryTime();
				if (expireCheck && expiryTime != void 0 && expiryTime <= now) {
					store.removeCookie(c.domain, c.path, c.key, () => {});
					return false;
				}
				return true;
			}
			store.findCookies(host, allPaths ? null : path, this.allowSpecialUseDomain, (err, cookies) => {
				if (err) {
					cb(err);
					return;
				}
				if (cookies == null) {
					cb(null, []);
					return;
				}
				cookies = cookies.filter(matchingCookie);
				if ("sort" in options && options.sort !== false) cookies = cookies.sort(cookieCompare);
				const now2 = /* @__PURE__ */ new Date();
				for (const cookie of cookies) cookie.lastAccessed = now2;
				cb(null, cookies);
			});
			return promiseCallback.promise;
		}
		/**
		* Synchronously retrieve the list of cookies that can be sent in a Cookie header for the
		* current URL.
		*
		* <strong>Note</strong>: Only works if the configured Store is also synchronous.
		*
		* @remarks
		* - The array of cookies returned will be sorted according to {@link cookieCompare}.
		*
		* - The {@link Cookie.lastAccessed} property will be updated on all returned cookies.
		*
		* @param url - The domain to store the cookie with.
		* @param options - Configuration settings to use when retrieving the cookies.
		*/
		getCookiesSync(url, options) {
			return this.callSync(this.getCookies.bind(this, url, options)) ?? [];
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		getCookieString(url, options, callback) {
			if (typeof options === "function") {
				callback = options;
				options = void 0;
			}
			const promiseCallback = createPromiseCallback(callback);
			const next = function(err, cookies) {
				if (err) promiseCallback.callback(err);
				else promiseCallback.callback(null, cookies?.sort(cookieCompare).map((c) => c.cookieString()).join("; "));
			};
			this.getCookies(url, options, next);
			return promiseCallback.promise;
		}
		/**
		* Synchronous version of `.getCookieString()`. Accepts the same options as `.getCookies()` but returns a string suitable for a
		* `Cookie` header rather than an Array.
		*
		* <strong>Note</strong>: Only works if the configured Store is also synchronous.
		*
		* @param url - The domain to store the cookie with.
		* @param options - Configuration settings to use when retrieving the cookies.
		*/
		getCookieStringSync(url, options) {
			return this.callSync(options ? this.getCookieString.bind(this, url, options) : this.getCookieString.bind(this, url)) ?? "";
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		getSetCookieStrings(url, options, callback) {
			if (typeof options === "function") {
				callback = options;
				options = void 0;
			}
			const promiseCallback = createPromiseCallback(callback);
			const next = function(err, cookies) {
				if (err) promiseCallback.callback(err);
				else promiseCallback.callback(null, cookies?.map((c) => {
					return c.toString();
				}));
			};
			this.getCookies(url, options, next);
			return promiseCallback.promise;
		}
		/**
		* Synchronous version of `.getSetCookieStrings()`. Returns an array of strings suitable for `Set-Cookie` headers.
		* Accepts the same options as `.getCookies()`.
		*
		* <strong>Note</strong>: Only works if the configured Store is also synchronous.
		*
		* @param url - The domain to store the cookie with.
		* @param options - Configuration settings to use when retrieving the cookies.
		*/
		getSetCookieStringsSync(url, options = {}) {
			return this.callSync(this.getSetCookieStrings.bind(this, url, options)) ?? [];
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		serialize(callback) {
			const promiseCallback = createPromiseCallback(callback);
			let type = this.store.constructor.name;
			if (isObject$1(type)) type = null;
			const serialized = {
				version: `tough-cookie@${version}`,
				storeType: type,
				rejectPublicSuffixes: this.rejectPublicSuffixes,
				enableLooseMode: this.enableLooseMode,
				allowSpecialUseDomain: this.allowSpecialUseDomain,
				prefixSecurity: getNormalizedPrefixSecurity(this.prefixSecurity),
				cookies: []
			};
			if (typeof this.store.getAllCookies !== "function") return promiseCallback.reject(/* @__PURE__ */ new Error("store does not support getAllCookies and cannot be serialized"));
			this.store.getAllCookies((err, cookies) => {
				if (err) {
					promiseCallback.callback(err);
					return;
				}
				if (cookies == null) {
					promiseCallback.callback(null, serialized);
					return;
				}
				serialized.cookies = cookies.map((cookie) => {
					const serializedCookie = cookie.toJSON();
					delete serializedCookie.creationIndex;
					return serializedCookie;
				});
				promiseCallback.callback(null, serialized);
			});
			return promiseCallback.promise;
		}
		/**
		* Serialize the CookieJar if the underlying store supports `.getAllCookies`.
		*
		* <strong>Note</strong>: Only works if the configured Store is also synchronous.
		*/
		serializeSync() {
			return this.callSync((callback) => {
				this.serialize(callback);
			});
		}
		/**
		* Alias of {@link CookieJar.serializeSync}. Allows the cookie to be serialized
		* with `JSON.stringify(cookieJar)`.
		*/
		toJSON() {
			return this.serializeSync();
		}
		/**
		* Use the class method CookieJar.deserialize instead of calling this directly
		* @internal
		*/
		_importCookies(serialized, callback) {
			let cookies = void 0;
			if (serialized && typeof serialized === "object" && inOperator("cookies", serialized) && Array.isArray(serialized.cookies)) cookies = serialized.cookies;
			if (!cookies) {
				callback(/* @__PURE__ */ new Error("serialized jar has no cookies array"), void 0);
				return;
			}
			cookies = cookies.slice();
			const putNext = (err) => {
				if (err) {
					callback(err, void 0);
					return;
				}
				if (Array.isArray(cookies)) {
					if (!cookies.length) {
						callback(err, this);
						return;
					}
					let cookie;
					try {
						cookie = Cookie.fromJSON(cookies.shift());
					} catch (e) {
						callback(e instanceof Error ? e : /* @__PURE__ */ new Error(), void 0);
						return;
					}
					if (cookie === void 0) {
						putNext(null);
						return;
					}
					this.store.putCookie(cookie, putNext);
				}
			};
			putNext(null);
		}
		/**
		* @internal
		*/
		_importCookiesSync(serialized) {
			this.callSync(this._importCookies.bind(this, serialized));
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		clone(newStore, callback) {
			if (typeof newStore === "function") {
				callback = newStore;
				newStore = void 0;
			}
			const promiseCallback = createPromiseCallback(callback);
			const cb = promiseCallback.callback;
			this.serialize((err, serialized) => {
				if (err) return promiseCallback.reject(err);
				return _CookieJar.deserialize(serialized ?? "", newStore, cb);
			});
			return promiseCallback.promise;
		}
		/**
		* @internal
		*/
		_cloneSync(newStore) {
			const cloneFn = newStore && typeof newStore !== "function" ? this.clone.bind(this, newStore) : this.clone.bind(this);
			return this.callSync((callback) => {
				cloneFn(callback);
			});
		}
		/**
		* Produces a deep clone of this CookieJar. Modifications to the original do
		* not affect the clone, and vice versa.
		*
		* <strong>Note</strong>: Only works if both the configured Store and destination
		* Store are synchronous.
		*
		* @remarks
		* - When no {@link Store} is provided, a new {@link MemoryCookieStore} will be used.
		*
		* - Transferring between store types is supported so long as the source
		*     implements `.getAllCookies()` and the destination implements `.putCookie()`.
		*
		* @param newStore - The target {@link Store} to clone cookies into.
		*/
		cloneSync(newStore) {
			if (!newStore) return this._cloneSync();
			if (!newStore.synchronous) throw new Error("CookieJar clone destination store is not synchronous; use async API instead.");
			return this._cloneSync(newStore);
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		removeAllCookies(callback) {
			const promiseCallback = createPromiseCallback(callback);
			const cb = promiseCallback.callback;
			const store = this.store;
			if (typeof store.removeAllCookies === "function" && store.removeAllCookies !== Store.prototype.removeAllCookies) {
				store.removeAllCookies(cb);
				return promiseCallback.promise;
			}
			store.getAllCookies((err, cookies) => {
				if (err) {
					cb(err);
					return;
				}
				if (!cookies) cookies = [];
				if (cookies.length === 0) {
					cb(null, void 0);
					return;
				}
				let completedCount = 0;
				const removeErrors = [];
				const removeCookieCb = function removeCookieCb2(removeErr) {
					if (removeErr) removeErrors.push(removeErr);
					completedCount++;
					if (completedCount === cookies.length) {
						if (removeErrors[0]) cb(removeErrors[0]);
						else cb(null, void 0);
						return;
					}
				};
				cookies.forEach((cookie) => {
					store.removeCookie(cookie.domain, cookie.path, cookie.key, removeCookieCb);
				});
			});
			return promiseCallback.promise;
		}
		/**
		* Removes all cookies from the CookieJar.
		*
		* <strong>Note</strong>: Only works if the configured Store is also synchronous.
		*
		* @remarks
		* - This is a new backwards-compatible feature of tough-cookie version 2.5,
		*     so not all Stores will implement it efficiently. For Stores that do not
		*     implement `removeAllCookies`, the fallback is to call `removeCookie` after
		*     `getAllCookies`.
		*
		* - If `getAllCookies` fails or isn't implemented in the Store, an error is returned.
		*
		* - If one or more of the `removeCookie` calls fail, only the first error is returned.
		*/
		removeAllCookiesSync() {
			this.callSync((callback) => {
				this.removeAllCookies(callback);
			});
		}
		/**
		* @internal No doc because this is the overload implementation
		*/
		static deserialize(strOrObj, store, callback) {
			if (typeof store === "function") {
				callback = store;
				store = void 0;
			}
			const promiseCallback = createPromiseCallback(callback);
			let serialized;
			if (typeof strOrObj === "string") try {
				serialized = JSON.parse(strOrObj);
			} catch (e) {
				return promiseCallback.reject(e instanceof Error ? e : /* @__PURE__ */ new Error());
			}
			else serialized = strOrObj;
			const readSerializedProperty = (property) => {
				return serialized && typeof serialized === "object" && inOperator(property, serialized) ? serialized[property] : void 0;
			};
			const readSerializedBoolean = (property) => {
				const value = readSerializedProperty(property);
				return typeof value === "boolean" ? value : void 0;
			};
			const readSerializedString = (property) => {
				const value = readSerializedProperty(property);
				return typeof value === "string" ? value : void 0;
			};
			const jar = new _CookieJar(store, {
				rejectPublicSuffixes: readSerializedBoolean("rejectPublicSuffixes"),
				looseMode: readSerializedBoolean("enableLooseMode"),
				allowSpecialUseDomain: readSerializedBoolean("allowSpecialUseDomain"),
				prefixSecurity: getNormalizedPrefixSecurity(readSerializedString("prefixSecurity") ?? "silent")
			});
			jar._importCookies(serialized, (err) => {
				if (err) {
					promiseCallback.callback(err);
					return;
				}
				promiseCallback.callback(null, jar);
			});
			return promiseCallback.promise;
		}
		/**
		* A new CookieJar is created and the serialized {@link Cookie} values are added to
		* the underlying store. Each {@link Cookie} is added via `store.putCookie(...)` in
		* the order in which they appear in the serialization.
		*
		* <strong>Note</strong>: Only works if the configured Store is also synchronous.
		*
		* @remarks
		* - When no {@link Store} is provided, a new {@link MemoryCookieStore} will be used.
		*
		* - As a convenience, if `strOrObj` is a string, it is passed through `JSON.parse` first.
		*
		* @param strOrObj - A JSON string or object representing the deserialized cookies.
		* @param store - The underlying store to persist the deserialized cookies into.
		*/
		static deserializeSync(strOrObj, store) {
			const serialized = typeof strOrObj === "string" ? JSON.parse(strOrObj) : strOrObj;
			const readSerializedProperty = (property) => {
				return serialized && typeof serialized === "object" && inOperator(property, serialized) ? serialized[property] : void 0;
			};
			const readSerializedBoolean = (property) => {
				const value = readSerializedProperty(property);
				return typeof value === "boolean" ? value : void 0;
			};
			const readSerializedString = (property) => {
				const value = readSerializedProperty(property);
				return typeof value === "string" ? value : void 0;
			};
			const jar = new _CookieJar(store, {
				rejectPublicSuffixes: readSerializedBoolean("rejectPublicSuffixes"),
				looseMode: readSerializedBoolean("enableLooseMode"),
				allowSpecialUseDomain: readSerializedBoolean("allowSpecialUseDomain"),
				prefixSecurity: getNormalizedPrefixSecurity(readSerializedString("prefixSecurity") ?? "silent")
			});
			if (!jar.store.synchronous) throw new Error("CookieJar store is not synchronous; use async API instead.");
			jar._importCookiesSync(serialized);
			return jar;
		}
		/**
		* Alias of {@link CookieJar.deserializeSync}.
		*
		* @remarks
		* - When no {@link Store} is provided, a new {@link MemoryCookieStore} will be used.
		*
		* - As a convenience, if `strOrObj` is a string, it is passed through `JSON.parse` first.
		*
		* @param jsonString - A JSON string or object representing the deserialized cookies.
		* @param store - The underlying store to persist the deserialized cookies into.
		*/
		static fromJSON(jsonString, store) {
			return _CookieJar.deserializeSync(jsonString, store);
		}
	};
	/*!
	* Copyright (c) 2015-2020, Salesforce.com, Inc.
	* All rights reserved.
	*
	* Redistribution and use in source and binary forms, with or without
	* modification, are permitted provided that the following conditions are met:
	*
	* 1. Redistributions of source code must retain the above copyright notice,
	* this list of conditions and the following disclaimer.
	*
	* 2. Redistributions in binary form must reproduce the above copyright notice,
	* this list of conditions and the following disclaimer in the documentation
	* and/or other materials provided with the distribution.
	*
	* 3. Neither the name of Salesforce.com nor the names of its contributors may
	* be used to endorse or promote products derived from this software without
	* specific prior written permission.
	*
	* THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
	* AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
	* IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
	* ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
	* LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
	* CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
	* SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
	* INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
	* CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
	* ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
	* POSSIBILITY OF SUCH DAMAGE.
	*/
	//#endregion
	//#region src/core/utils/internal/json-parse.ts
	/**
	* Parses a given value into a JSON.
	* Does not throw an exception on an invalid JSON string.
	*/
	function jsonParse(value) {
		try {
			return JSON.parse(value);
		} catch {
			return;
		}
	}
	//#endregion
	//#region src/core/utils/cookie-store.ts
	var CookieStore = class {
		#storageKey = "__msw-cookie-store__";
		#jar;
		#memoryStore;
		constructor() {
			invariant$1(typeof localStorage !== "undefined", "Failed to create a CookieStore: `localStorage` is not available in this environment. This is likely an issue with your environment, which has been detected as browser (or browser-like) environment and must implement global browser APIs correctly.");
			this.#memoryStore = new MemoryCookieStore();
			this.#memoryStore.idx = this.getCookieStoreIndex();
			this.#jar = new CookieJar(this.#memoryStore);
		}
		getCookies(url) {
			return this.#jar.getCookiesSync(url);
		}
		async setCookie(cookieName, url) {
			await this.#jar.setCookie(cookieName, url);
			this.persist();
		}
		getCookieStoreIndex() {
			if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") return {};
			const cookiesString = localStorage.getItem(this.#storageKey);
			if (cookiesString == null) return {};
			const rawCookies = jsonParse(cookiesString);
			if (rawCookies == null) return {};
			const cookies = {};
			for (const rawCookie of rawCookies) {
				const cookie = Cookie.fromJSON(rawCookie);
				if (cookie != null && cookie.domain != null && cookie.path != null) {
					cookies[cookie.domain] ||= {};
					cookies[cookie.domain][cookie.path] ||= {};
					cookies[cookie.domain][cookie.path][cookie.key] = cookie;
				}
			}
			return cookies;
		}
		persist() {
			if (typeof localStorage === "undefined" || typeof localStorage.setItem !== "function") return;
			const data = [];
			const { idx } = this.#memoryStore;
			for (const domain in idx) for (const path in idx[domain]) for (const key in idx[domain][path]) data.push(idx[domain][path][key].toJSON());
			try {
				localStorage.setItem(this.#storageKey, JSON.stringify(data));
			} catch {
				return;
			}
		}
	};
	const cookieStore = isNodeProcess() ? null : new CookieStore();
	//#endregion
	//#region src/core/utils/request/get-request-cookies.ts
	function parseCookies(input) {
		const parsedCookies = parseCookie(input);
		const cookies = {};
		for (const cookieName in parsedCookies) if (typeof parsedCookies[cookieName] !== "undefined") cookies[cookieName] = parsedCookies[cookieName];
		return cookies;
	}
	function getAllDocumentCookies() {
		return parseCookies(document.cookie);
	}
	/**
	* Returns whether the given request would carry cookies,
	* based on its `credentials` mode.
	*/
	function includesCredentials(request) {
		switch (request.credentials) {
			case "same-origin": return typeof location !== "undefined" && location.origin === new URL(request.url).origin;
			case "include": return true;
			default: return false;
		}
	}
	function getDocumentCookies() {
		if (typeof document === "undefined") return {};
		return getAllDocumentCookies();
	}
	function getAllRequestCookies(request) {
		const requestCookieHeader = request.headers.get("cookie");
		const cookiesFromHeaders = requestCookieHeader ? parseCookies(requestCookieHeader) : {};
		if (cookieStore === null || !includesCredentials(request)) return cookiesFromHeaders;
		const cookiesFromDocument = getDocumentCookies();
		const cookiesFromStore = cookieStore.getCookies(request.url);
		const storedCookiesObject = Object.fromEntries(cookiesFromStore.map((cookie) => [cookie.key, cookie.value]));
		return {
			...cookiesFromDocument,
			...storedCookiesObject,
			...cookiesFromHeaders
		};
	}
	//#endregion
	//#region src/http/http-handler.ts
	let HttpMethods = /* @__PURE__ */ function(HttpMethods) {
		HttpMethods["HEAD"] = "HEAD";
		HttpMethods["GET"] = "GET";
		HttpMethods["POST"] = "POST";
		HttpMethods["PUT"] = "PUT";
		HttpMethods["PATCH"] = "PATCH";
		HttpMethods["OPTIONS"] = "OPTIONS";
		HttpMethods["DELETE"] = "DELETE";
		return HttpMethods;
	}({});
	/**
	* Request handler for HTTP requests.
	* Provides request matching based on method and URL.
	*/
	var HttpHandler = class extends RequestHandler {
		constructor(method, predicate, resolver, options) {
			const displayPath = typeof predicate === "function" ? "[custom predicate]" : predicate;
			super({
				info: {
					header: `${method}${displayPath ? ` ${displayPath}` : ""}`,
					path: predicate,
					method
				},
				resolver,
				options
			});
			this.checkRedundantQueryParameters();
		}
		checkRedundantQueryParameters() {
			const { method, path } = this.info;
			if (!path || path instanceof RegExp || typeof path === "function") return;
			if (getCleanUrlString(path) === path) return;
			devUtils.warn(`Found a redundant usage of query parameters in the request handler URL for "${method} ${path}". Please match against a path instead and access query parameters using "new URL(request.url).searchParams" instead. Learn more: https://mswjs.io/docs/http/intercepting-requests#querysearch-parameters`);
		}
		async parse(args) {
			/**
			* @note CONNECT requests target an authority ("host:port"), not a URL.
			* HTTP handlers never match them.
			* @todo Match the authority against the handler path once
			* `http.connect()` is supported instead of bailing out.
			*/
			if (isStringEqual(args.request.method, "CONNECT")) return {
				match: {
					matches: false,
					params: {}
				},
				cookies: {}
			};
			const url = new URL(args.request.url);
			const cookies = getAllRequestCookies(args.request);
			/**
			* Handle custom predicate functions.
			* @note Invoke this during parsing so the user can parse the path parameters
			* manually. Otherwise, `params` is always an empty object, which isn't nice.
			*/
			if (typeof this.info.path === "function") {
				const customPredicateResult = await this.info.path({
					request: args.request,
					cookies
				});
				return {
					match: typeof customPredicateResult === "boolean" ? {
						matches: customPredicateResult,
						params: {}
					} : customPredicateResult,
					cookies
				};
			}
			return {
				match: this.info.path ? matchRequestUrl(url, this.info.path, args.resolutionContext?.baseUrl) : {
					matches: false,
					params: {}
				},
				cookies
			};
		}
		async predicate(args) {
			const hasMatchingMethod = this.matchMethod(args.request.method);
			const hasMatchingUrl = args.parsedResult.match.matches;
			return hasMatchingMethod && hasMatchingUrl;
		}
		matchMethod(actualMethod) {
			return this.info.method instanceof RegExp ? this.info.method.test(actualMethod) : isStringEqual(this.info.method, actualMethod);
		}
		extendResolverArgs(args) {
			return {
				params: args.parsedResult.match?.params || {},
				cookies: args.parsedResult.cookies
			};
		}
		async log(args) {
			const publicUrl = toPublicUrl(args.request.url);
			const loggedRequest = await serializeRequest(args.request);
			const loggedResponse = await serializeResponse(args.response);
			const statusColor = getStatusCodeColor(loggedResponse.status);
			console.groupCollapsed(devUtils.formatMessage(`${getTimestamp()} ${args.request.method} ${publicUrl} (%c${loggedResponse.status} ${loggedResponse.statusText}%c)`), `color:${statusColor}`, "color:inherit");
			console.log("Request", loggedRequest);
			console.log("Handler:", this);
			console.log("Response", loggedResponse);
			console.groupEnd();
		}
	};
	//#endregion
	//#region src/http/http.ts
	function createHttpHandler(method) {
		return (predicate, resolver, options = {}) => {
			return new HttpHandler(method, predicate, resolver, options);
		};
	}
	/**
	* A namespace to intercept and mock HTTP requests.
	*
	* @example
	* http.get('/user', resolver)
	* http.post('/post/:id', resolver)
	*
	* @see {@link https://mswjs.io/docs/api/http `http` API reference}
	*/
	const http = {
		all: createHttpHandler(/.+/),
		head: createHttpHandler("HEAD"),
		get: createHttpHandler("GET"),
		post: createHttpHandler("POST"),
		put: createHttpHandler("PUT"),
		delete: createHttpHandler("DELETE"),
		patch: createHttpHandler("PATCH"),
		options: createHttpHandler("OPTIONS")
	};
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/has-configurable-global-Cew-dYqk.js
	var PatchesRegistry = class {
		#replacements = /* @__PURE__ */ new Map();
		applyPatch(owner, key, getNextValue) {
			const ownerReplacements = this.#replacements.get(owner);
			invariant$1(!ownerReplacements?.has(key), `Failed to replace a global value at "${String(key)}": already replaced.`);
			const match = getDeepPropertyDescriptor(owner, key);
			if (typeof match === "undefined") {
				console.warn(`Failed to replace a global value at "${String(key)}": not a global value.`);
				return () => {};
			}
			if (match.descriptor.configurable) Object.defineProperty(owner, key, {
				value: getNextValue(owner[key]),
				enumerable: true,
				configurable: true
			});
			else if (match.descriptor.writable) owner[key] = getNextValue(owner[key]);
			else throw new Error(`Failed to patch a non-configurable non-writable property "${key.toString()}"`);
			const restorePatch = () => {
				const currentReplacements = this.#replacements.get(owner);
				if (!currentReplacements?.has(key)) return;
				if (match.owner === owner)
 /**
				* @note Restoring non-configurable properties works as long as "writable: true"
				* and none of the other descriptor properties except for "value" have changed.
				*/
				Object.defineProperty(match.owner, key, match.descriptor);
				else
 /**
				* @todo Delete the proxy property set by the registry.
				* If the match's owner isn't the original owner, the property is likely nested in the prototype.
				* The registry does not meddle with those, they are left intact.
				*/
				Reflect.deleteProperty(owner, key);
				currentReplacements.delete(key);
				if (currentReplacements.size === 0) this.#replacements.delete(owner);
			};
			if (ownerReplacements) ownerReplacements.set(key, restorePatch);
			else this.#replacements.set(owner, /* @__PURE__ */ new Map([[key, restorePatch]]));
			return restorePatch;
		}
		restoreAllPatches() {
			const errors = [];
			for (const [, ownerReplacements] of this.#replacements) for (const [, restorePatch] of ownerReplacements) try {
				restorePatch();
			} catch (error) {
				if (error instanceof Error) errors.push(error);
				else throw error;
			}
			if (errors.length > 0) throw new AggregateError(errors, "FOO!");
		}
	};
	const patchesRegistry = new PatchesRegistry();
	/**
	* Returns a property descriptor for the given property on the owner.
	* Walks down the prototype chain if the property does not exist on the owner.
	* Handy for getting a global property descriptor where `globalThis` is
	* replaced with a controlled class (e.g. ServiceWorkerGlobalScope).
	*/
	function getDeepPropertyDescriptor(owner, key) {
		let currentOwner = owner;
		let descriptor;
		while (currentOwner) {
			descriptor = Object.getOwnPropertyDescriptor(currentOwner, key);
			if (descriptor) return {
				owner: currentOwner,
				descriptor
			};
			currentOwner = Object.getPrototypeOf(currentOwner);
		}
	}
	/**
	* Returns a boolean indicating whether the given global property
	* is defined and is configurable.
	*/
	function hasConfigurableGlobal(propertyName) {
		const match = getDeepPropertyDescriptor(globalThis, propertyName);
		if (typeof match === "undefined") return false;
		const { descriptor } = match;
		if (typeof descriptor.get === "function" && typeof descriptor.get() === "undefined") return false;
		if (typeof descriptor.get === "undefined" && descriptor.value == null) return false;
		if (typeof descriptor.set === "undefined" && !descriptor.configurable) {
			console.error(`[MSW] Failed to apply interceptor: the global \`${propertyName}\` property is non-configurable. This is likely an issue with your environment. If you are using a framework, please open an issue about this in their repository.`);
			return false;
		}
		return true;
	}
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/interceptors/WebSocket/index.js
	var WebSocketConnectionEvent$2 = class extends TypedEvent {
		constructor(data) {
			super("connection", { data });
			this.client = data.client;
			this.server = data.server;
			this.info = data.info;
		}
	};
	function bindEvent(target, event) {
		Object.defineProperties(event, {
			target: {
				value: target,
				enumerable: true,
				writable: true
			},
			currentTarget: {
				value: target,
				enumerable: true,
				writable: true
			}
		});
		return event;
	}
	const kCancelable = Symbol("kCancelable");
	const kDefaultPrevented = Symbol("kDefaultPrevented");
	/**
	* A `MessageEvent` superset that supports event cancellation
	* in Node.js. It's rather non-intrusive so it can be safely
	* used in the browser as well.
	*
	* @see https://github.com/nodejs/node/issues/51767
	*/
	var CancelableMessageEvent = class extends MessageEvent {
		constructor(type, init) {
			super(type, init);
			this[kCancelable] = !!init.cancelable;
			this[kDefaultPrevented] = false;
		}
		get cancelable() {
			return this[kCancelable];
		}
		set cancelable(nextCancelable) {
			this[kCancelable] = nextCancelable;
		}
		get defaultPrevented() {
			return this[kDefaultPrevented];
		}
		set defaultPrevented(nextDefaultPrevented) {
			this[kDefaultPrevented] = nextDefaultPrevented;
		}
		preventDefault() {
			if (this.cancelable && !this[kDefaultPrevented]) this[kDefaultPrevented] = true;
		}
	};
	var CloseEvent = class extends Event {
		constructor(type, init = {}) {
			super(type, init);
			this.code = init.code === void 0 ? 0 : init.code;
			this.reason = init.reason === void 0 ? "" : init.reason;
			this.wasClean = init.wasClean === void 0 ? false : init.wasClean;
		}
	};
	var CancelableCloseEvent = class extends CloseEvent {
		constructor(type, init = {}) {
			super(type, init);
			this[kCancelable] = !!init.cancelable;
			this[kDefaultPrevented] = false;
		}
		get cancelable() {
			return this[kCancelable];
		}
		set cancelable(nextCancelable) {
			this[kCancelable] = nextCancelable;
		}
		get defaultPrevented() {
			return this[kDefaultPrevented];
		}
		set defaultPrevented(nextDefaultPrevented) {
			this[kDefaultPrevented] = nextDefaultPrevented;
		}
		preventDefault() {
			if (this.cancelable && !this[kDefaultPrevented]) this[kDefaultPrevented] = true;
		}
	};
	const kExtensionContext = Symbol("kExtensionContext");
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
	var WebSocketExtension = class {
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
		apply(connection) {
			connection.client.extension = this;
			connection.server.extension = this;
		}
	};
	/**
	* Assert that the given message is raw WebSocket data.
	* Without a protocol, a connection can only carry raw data.
	*/
	function toWebSocketData(message) {
		if (typeof message === "string" || message instanceof ArrayBuffer || message instanceof Blob) return message;
		if (ArrayBuffer.isView(message) && message.buffer instanceof ArrayBuffer) return new Uint8Array(message.buffer, message.byteOffset, message.byteLength);
		throw new TypeError(`Failed to send a message of type "${typeof message}": a connection without an extension can only send strings, Blob, ArrayBuffer, or ArrayBufferView`);
	}
	/**
	* Iterate over the values of the given protocol result.
	* A generator's return value, if any, counts as its last value.
	*
	* Delegating via `yield*` forwards early termination of this
	* generator (e.g. a `break` or an error in the consumer's loop)
	* to the underlying iterator so it can clean up after itself.
	*/
	function* iterateWebSocketExtensionResult(result) {
		if (result === void 0) return;
		if (isIterator(result)) {
			const returnValue = yield* { [Symbol.iterator]: () => result };
			if (returnValue !== void 0) yield returnValue;
			return;
		}
		yield result;
	}
	/**
	* @note Only objects with a `next()` method count as iterators.
	* Iterables that are not iterators (strings, arrays, typed arrays)
	* are intentionally excluded so array-shaped messages remain unambiguous.
	*/
	function isIterator(value) {
		return typeof value === "object" && value !== null && typeof Reflect.get(value, "next") === "function";
	}
	const kEmitter$1 = Symbol("kEmitter");
	const kBoundListener$1 = Symbol("kBoundListener");
	/**
	* The WebSocket client instance represents an incoming
	* client connection. The user can control the connection,
	* send and receive events.
	*/
	var WebSocketClientConnection = class {
		constructor(socket, transport) {
			this.socket = socket;
			this.transport = transport;
			this.id = createRequestId();
			this.url = new URL(socket.url);
			this[kEmitter$1] = new EventTarget();
			/**
			* Emit the "open" event on the "client" connection once the
			* client connection is open. This is either the mocked connection
			* opening or, for passthrough connections, the original server
			* connection opening (forwarded to the client by the interceptor).
			*/
			this.socket.addEventListener("open", () => {
				this[kEmitter$1].dispatchEvent(bindEvent(this.socket, new Event("open")));
			}, { once: true });
			this.transport.addEventListener("outgoing", (event) => {
				const messages = this.extension ? iterateWebSocketExtensionResult(this.extension.decode(event.data, this.#getMessageContext())) : [event.data];
				let defaultPrevented = false;
				for (const data of messages) {
					const message = bindEvent(this.socket, new CancelableMessageEvent("message", {
						data,
						origin: event.origin,
						cancelable: true
					}));
					this[kEmitter$1].dispatchEvent(message);
					defaultPrevented ||= message.defaultPrevented;
				}
				if (defaultPrevented) event.preventDefault();
			});
			/**
			* Emit the "close" event on the "client" connection
			* whenever the underlying transport is closed.
			* @note "client.close()" does NOT dispatch the "close"
			* event on the WebSocket because it uses non-configurable
			* close status code. Thus, we listen to the transport
			* instead of the WebSocket's "close" event.
			*/
			this.transport.addEventListener("close", (event) => {
				this[kEmitter$1].dispatchEvent(bindEvent(this.socket, new CloseEvent("close", event)));
			});
		}
		/**
		* Listen for the outgoing events from the connected WebSocket client.
		*/
		addEventListener(type, listener, options) {
			if (!Reflect.has(listener, kBoundListener$1)) {
				const boundListener = listener.bind(this.socket);
				Object.defineProperty(listener, kBoundListener$1, {
					value: boundListener,
					enumerable: false,
					configurable: false
				});
			}
			this[kEmitter$1].addEventListener(type, Reflect.get(listener, kBoundListener$1), options);
		}
		/**
		* Removes the listener for the given event.
		*/
		removeEventListener(event, listener, options) {
			this[kEmitter$1].removeEventListener(event, Reflect.get(listener, kBoundListener$1), options);
		}
		/**
		* Send data to the connected client.
		*/
		send(data) {
			if (!this.extension) {
				this.transport.send(toWebSocketData(data));
				return;
			}
			for (const frame of iterateWebSocketExtensionResult(this.extension.encode(data, this.#getMessageContext()))) this.transport.send(frame);
		}
		#getMessageContext() {
			const context = this[kExtensionContext];
			if (!context) throw new Error(`Failed to apply the extension to the client connection "${this.url.href}": the connection context is missing`);
			return {
				...context,
				connection: this
			};
		}
		/**
		* Close the WebSocket connection.
		* @param {number} code A status code (see https://www.rfc-editor.org/rfc/rfc6455#section-7.4.1).
		* @param {string} reason A custom connection close reason.
		*/
		close(code, reason) {
			this.transport.close(code, reason);
		}
	};
	const WEBSOCKET_CLOSE_CODE_RANGE_ERROR = "InvalidAccessError: close code out of user configurable range";
	const kPassthroughPromise = Symbol("kPassthroughPromise");
	const kOnSend = Symbol("kOnSend");
	const kClose = Symbol("kClose");
	var WebSocketOverride = class extends EventTarget {
		static {
			this.CONNECTING = 0;
		}
		static {
			this.OPEN = 1;
		}
		static {
			this.CLOSING = 2;
		}
		static {
			this.CLOSED = 3;
		}
		constructor(url, protocols) {
			super();
			this.CONNECTING = 0;
			this.OPEN = 1;
			this.CLOSING = 2;
			this.CLOSED = 3;
			this._onopen = null;
			this._onmessage = null;
			this._onerror = null;
			this._onclose = null;
			this.url = resolveWebSocketUrl(url);
			this.protocol = "";
			this.extensions = "";
			this.binaryType = "blob";
			this.readyState = this.CONNECTING;
			this.bufferedAmount = 0;
			this[kPassthroughPromise] = Promise.withResolvers();
			queueMicrotask(async () => {
				if (await this[kPassthroughPromise].promise) return;
				this.protocol = typeof protocols === "string" ? protocols : Array.isArray(protocols) && protocols.length > 0 ? protocols[0] : "";
				/**
				* @note Check that nothing has prevented this connection
				* (e.g. called `client.close()` in the connection listener).
				* If the connection has been prevented, never dispatch the open event,.
				*/
				if (this.readyState === this.CONNECTING) {
					this.readyState = this.OPEN;
					this.dispatchEvent(bindEvent(this, new Event("open")));
				}
			});
		}
		set onopen(listener) {
			this.removeEventListener("open", this._onopen);
			this._onopen = listener;
			if (listener !== null) this.addEventListener("open", listener);
		}
		get onopen() {
			return this._onopen;
		}
		set onmessage(listener) {
			this.removeEventListener("message", this._onmessage);
			this._onmessage = listener;
			if (listener !== null) this.addEventListener("message", listener);
		}
		get onmessage() {
			return this._onmessage;
		}
		set onerror(listener) {
			this.removeEventListener("error", this._onerror);
			this._onerror = listener;
			if (listener !== null) this.addEventListener("error", listener);
		}
		get onerror() {
			return this._onerror;
		}
		set onclose(listener) {
			this.removeEventListener("close", this._onclose);
			this._onclose = listener;
			if (listener !== null) this.addEventListener("close", listener);
		}
		get onclose() {
			return this._onclose;
		}
		/**
		* @see https://websockets.spec.whatwg.org/#ref-for-dom-websocket-send%E2%91%A0
		*/
		send(data) {
			if (this.readyState === this.CONNECTING) {
				this.close();
				throw new DOMException("InvalidStateError");
			}
			if (this.readyState === this.CLOSING || this.readyState === this.CLOSED) return;
			this.bufferedAmount += getDataSize(data);
			queueMicrotask(() => {
				this.bufferedAmount = 0;
				/**
				* @note Notify the parent about outgoing data.
				* This notifies the transport and the connection
				* listens to the outgoing data to emit the "message" event.
				*/
				this[kOnSend]?.(data);
			});
		}
		close(code = 1e3, reason) {
			invariant$1(code, WEBSOCKET_CLOSE_CODE_RANGE_ERROR);
			invariant$1(code === 1e3 || code >= 3e3 && code <= 4999, WEBSOCKET_CLOSE_CODE_RANGE_ERROR);
			this[kClose](code, reason);
		}
		[kClose](code = 1e3, reason, wasClean = true) {
			/**
			* @note Move this check here so that even internal closures,
			* like those triggered by the `server` connection, are not
			* performed twice.
			*/
			if (this.readyState === this.CLOSING || this.readyState === this.CLOSED) return;
			this.readyState = this.CLOSING;
			queueMicrotask(() => {
				this.readyState = this.CLOSED;
				this.dispatchEvent(bindEvent(this, new CloseEvent("close", {
					code,
					reason,
					wasClean
				})));
				this._onopen = null;
				this._onmessage = null;
				this._onerror = null;
				this._onclose = null;
			});
		}
		addEventListener(type, listener, options) {
			return super.addEventListener(type, listener, options);
		}
		removeEventListener(type, callback, options) {
			return super.removeEventListener(type, callback, options);
		}
	};
	function getDataSize(data) {
		if (typeof data === "string") return data.length;
		if (data instanceof Blob) return data.size;
		return data.byteLength;
	}
	const kEmitter$2 = Symbol("kEmitter");
	const kBoundListener = Symbol("kBoundListener");
	const kSend = Symbol("kSend");
	/**
	* The WebSocket server instance represents the actual production
	* WebSocket server connection. It's idle by default but you can
	* establish it by calling `server.connect()`.
	*/
	var WebSocketServerConnection = class {
		constructor(client, transport, createConnection) {
			this.client = client;
			this.transport = transport;
			this.createConnection = createConnection;
			this[kEmitter$2] = new EventTarget();
			this.mockCloseController = new AbortController();
			this.realCloseController = new AbortController();
			this.transport.addEventListener("outgoing", (event) => {
				if (typeof this.realWebSocket === "undefined") return;
				queueMicrotask(() => {
					if (!event.defaultPrevented)
 /**
					* @note Use the internal send mechanism so consumers can tell
					* apart direct user calls to `server.send()` and internal calls.
					* E.g. MSW has to ignore this internal call to log out messages correctly.
					*/
					this[kSend](event.data);
				});
			});
			this.transport.addEventListener("incoming", this.handleIncomingMessage.bind(this));
		}
		/**
		* The `WebSocket` instance connected to the original server.
		* Accessing this before calling `server.connect()` will throw.
		*/
		get socket() {
			invariant$1(this.realWebSocket, "Cannot access \"socket\" on the original WebSocket server object: the connection is not open. Did you forget to call `server.connect()`?");
			return this.realWebSocket;
		}
		/**
		* The ready state of the connection to the original WebSocket server.
		* Equals `WebSocket.CLOSED` until `server.connect()` is called.
		*/
		get readyState() {
			return this.realWebSocket?.readyState ?? WebSocket.CLOSED;
		}
		/**
		* Open connection to the original WebSocket server.
		*/
		connect() {
			invariant$1(!this.realWebSocket || this.realWebSocket.readyState !== WebSocket.OPEN, "Failed to call \"connect()\" on the original WebSocket instance: the connection already open");
			const realWebSocket = this.createConnection();
			realWebSocket.binaryType = this.client.binaryType;
			realWebSocket.addEventListener("open", (event) => {
				this[kEmitter$2].dispatchEvent(bindEvent(this.realWebSocket, new Event("open", event)));
			}, { once: true });
			realWebSocket.addEventListener("message", (event) => {
				this.transport.dispatchEvent(bindEvent(this.realWebSocket, new MessageEvent("incoming", {
					data: event.data,
					origin: event.origin
				})));
			});
			this.client.addEventListener("close", (event) => {
				this.handleMockClose(event);
			}, { signal: this.mockCloseController.signal });
			realWebSocket.addEventListener("close", (event) => {
				this.handleRealClose(event);
			}, { signal: this.realCloseController.signal });
			realWebSocket.addEventListener("error", () => {
				const errorEvent = bindEvent(realWebSocket, new Event("error", { cancelable: true }));
				this[kEmitter$2].dispatchEvent(errorEvent);
				if (!errorEvent.defaultPrevented) this.client.dispatchEvent(bindEvent(this.client, new Event("error")));
			});
			this.realWebSocket = realWebSocket;
		}
		/**
		* Listen for the incoming events from the original WebSocket server.
		*/
		addEventListener(event, listener, options) {
			if (!Reflect.has(listener, kBoundListener)) {
				const boundListener = listener.bind(this.client);
				Object.defineProperty(listener, kBoundListener, {
					value: boundListener,
					enumerable: false
				});
			}
			this[kEmitter$2].addEventListener(event, Reflect.get(listener, kBoundListener), options);
		}
		/**
		* Remove the listener for the given event.
		*/
		removeEventListener(event, listener, options) {
			this[kEmitter$2].removeEventListener(event, Reflect.get(listener, kBoundListener), options);
		}
		/**
		* Send data to the original WebSocket server.
		* @example
		* server.send('hello')
		* server.send(new Blob(['hello']))
		* server.send(new TextEncoder().encode('hello'))
		*/
		send(data) {
			this.assertConnected();
			if (!this.extension) {
				this[kSend](toWebSocketData(data));
				return;
			}
			for (const frame of iterateWebSocketExtensionResult(this.extension.encode(data, this.#getMessageContext()))) this[kSend](frame);
		}
		#getMessageContext() {
			const context = this[kExtensionContext];
			if (!context) throw new Error(`Failed to apply the extension to the server connection "${this.client.url}": the connection context is missing`);
			return {
				...context,
				connection: this
			};
		}
		/**
		* Return the original WebSocket, throwing if
		* the connection to the original server was not established.
		*/
		assertConnected() {
			invariant$1(this.realWebSocket, "Failed to call \"server.send()\" for \"%s\": the connection is not open. Did you forget to call \"server.connect()\"?", this.client.url);
			return this.realWebSocket;
		}
		[kSend](data) {
			const realWebSocket = this.assertConnected();
			if (realWebSocket.readyState === WebSocket.CLOSING || realWebSocket.readyState === WebSocket.CLOSED) return;
			if (realWebSocket.readyState === WebSocket.CONNECTING) {
				realWebSocket.addEventListener("open", () => {
					realWebSocket.send(data);
				}, { once: true });
				return;
			}
			realWebSocket.send(data);
		}
		/**
		* Close the actual server connection.
		*/
		close() {
			const { realWebSocket } = this;
			invariant$1(realWebSocket, "Failed to close server connection for \"%s\": the connection is not open. Did you forget to call \"server.connect()\"?", this.client.url);
			this.realCloseController.abort();
			if (realWebSocket.readyState === WebSocket.CLOSING || realWebSocket.readyState === WebSocket.CLOSED) return;
			realWebSocket.close();
			queueMicrotask(() => {
				this[kEmitter$2].dispatchEvent(bindEvent(this.realWebSocket, new CancelableCloseEvent("close", {
					/**
					* @note `server.close()` in the interceptor
					* always results in clean closures.
					*/
					code: 1e3,
					cancelable: true
				})));
			});
		}
		handleIncomingMessage(event) {
			const messages = this.extension ? iterateWebSocketExtensionResult(this.extension.decode(event.data, this.#getMessageContext())) : [event.data];
			let defaultPrevented = false;
			for (const data of messages) {
				const messageEvent = bindEvent(event.target, new CancelableMessageEvent("message", {
					data,
					origin: event.origin,
					cancelable: true
				}));
				/**
				* @note Emit "message" event on the server connection
				* instance to let the interceptor know about these
				* incoming events from the original server. In that listener,
				* the interceptor can modify or skip the event forwarding
				* to the mock WebSocket instance.
				*/
				this[kEmitter$2].dispatchEvent(messageEvent);
				defaultPrevented ||= messageEvent.defaultPrevented;
			}
			/**
			* @note Forward the incoming server events to the client.
			* Preventing the default on the message event stops this.
			*/
			if (!defaultPrevented) this.client.dispatchEvent(bindEvent(
				/**
				* @note Bind the forwarded original server events
				* to the mock WebSocket instance so it would
				* dispatch them straight away.
				*/
				this.client,
				new MessageEvent("message", {
					data: event.data,
					origin: event.origin
				})
			));
		}
		handleMockClose(_event) {
			if (this.realWebSocket) this.realWebSocket.close();
		}
		handleRealClose(event) {
			this.mockCloseController.abort();
			const closeEvent = bindEvent(this.realWebSocket, new CancelableCloseEvent("close", {
				code: event.code,
				reason: event.reason,
				wasClean: event.wasClean,
				cancelable: true
			}));
			this[kEmitter$2].dispatchEvent(closeEvent);
			if (!closeEvent.defaultPrevented) this.client[kClose](event.code, event.reason);
		}
	};
	/**
	* Abstraction over the given mock `WebSocket` instance that allows
	* for controlling that instance (e.g. sending and receiving messages).
	*/
	var WebSocketClassTransport = class extends EventTarget {
		constructor(socket) {
			super();
			this.socket = socket;
			this.socket.addEventListener("close", (event) => {
				this.dispatchEvent(bindEvent(this.socket, new CloseEvent("close", event)));
			});
			/**
			* Emit the "outgoing" event on the transport
			* whenever the WebSocket client sends data ("ws.send()").
			*/
			this.socket[kOnSend] = (data) => {
				this.dispatchEvent(bindEvent(this.socket, new CancelableMessageEvent("outgoing", {
					data,
					origin: this.socket.url,
					cancelable: true
				})));
			};
		}
		addEventListener(type, callback, options) {
			return super.addEventListener(type, callback, options);
		}
		dispatchEvent(event) {
			return super.dispatchEvent(event);
		}
		send(data) {
			queueMicrotask(() => {
				if (this.socket.readyState === this.socket.CLOSING || this.socket.readyState === this.socket.CLOSED) return;
				const dispatchEvent = () => {
					this.socket.dispatchEvent(bindEvent(
						/**
						* @note Setting this event's "target" to the
						* WebSocket override instance is important.
						* This way it can tell apart original incoming events
						* (must be forwarded to the transport) from the
						* mocked message events like the one below
						* (must be dispatched on the client instance).
						*/
						this.socket,
						new MessageEvent("message", {
							data,
							origin: this.socket.url
						})
					));
				};
				if (this.socket.readyState === this.socket.CONNECTING) this.socket.addEventListener("open", () => {
					dispatchEvent();
				}, { once: true });
				else dispatchEvent();
			});
		}
		close(code, reason) {
			/**
			* @note Call the internal close method directly
			* to allow closing the connection with the status codes
			* that are non-configurable by the user (> 1000 <= 1015).
			*/
			this.socket[kClose](code, reason);
		}
	};
	/**
	* Share the Node-provided async context with the browser-built WebSocket
	* entry point without importing Node modules into the browser bundle.
	*/
	function runAsInternalConnection(callback) {
		const context = globalThis.__MSW_INTERNAL_CONNECTION_CONTEXT;
		if (context) return context.run(callback);
		return callback();
	}
	const logger$2 = createLogger("websocket");
	/**
	* Intercept the outgoing WebSocket connections created using
	* the global `WebSocket` class.
	*/
	var WebSocketInterceptor = class extends Interceptor {
		static {
			this.symbol = Symbol.for("websocket-interceptor");
		}
		constructor(options = {}) {
			super();
			this.extensions = options.extensions ?? [];
		}
		predicate() {
			return hasConfigurableGlobal("WebSocket");
		}
		setup() {
			logger$2.verbose("setup");
			const WebSocketProxy = new Proxy(globalThis.WebSocket, { construct: (target, args, newTarget) => {
				const [url, protocols] = args;
				logger$2.info("connection intercepted %o", {
					url: url.toString(),
					protocols
				});
				const createConnection = () => {
					return runAsInternalConnection(() => {
						return Reflect.construct(target, args, newTarget);
					});
				};
				const socket = new WebSocketOverride(url, protocols);
				const transport = new WebSocketClassTransport(socket);
				queueMicrotask(async () => {
					try {
						const server = new WebSocketServerConnection(socket, transport, createConnection);
						/**
						* @note The mocked connection plays the server endpoint of the
						* protocol unless a connection to the original server was
						* created, in which case the original server speaks for itself.
						* Check the creation, not the ready state: the original connection
						* may have already closed by now (e.g. when the client is kept open
						* past the original server closing), and the client must not be
						* handshaked twice.
						*/
						const isServerEndpoint = () => server["realWebSocket"] == null;
						/**
						* @note Register these before the client connection so the
						* protocol frames precede anything sent from its listeners.
						*/
						socket.addEventListener("open", () => {
							if (!isServerEndpoint()) return;
							for (const frame of iterateWebSocketExtensionResult(client.extension?.connect?.(context))) transport.send(frame);
						}, { once: true });
						transport.addEventListener("outgoing", (event) => {
							if (!isServerEndpoint()) return;
							for (const frame of iterateWebSocketExtensionResult(client.extension?.receive?.(event.data, context))) transport.send(frame);
						});
						const client = new WebSocketClientConnection(socket, transport);
						const context = {
							client,
							server,
							info: { protocols }
						};
						client[kExtensionContext] = context;
						server[kExtensionContext] = context;
						const extension = this.extensions.find((extension) => {
							return extension.match?.(context) ?? true;
						});
						extension?.apply(context);
						const hasConnectionListeners = this.emitter.listenerCount("connection") > 0;
						/**
						* @note Expose the extension's own API (e.g. rooms) on the
						* connection event. The event map is inferred from the extensions
						* this interceptor was given; `Object.assign` with a spread of
						* sources is untyped, which is what lets the event take that type.
						*/
						const extensionApis = [extension?.extend?.(context)];
						await this.emitter.emitAsPromise(Object.assign(new WebSocketConnectionEvent$2({
							client,
							server,
							info: context.info
						}), ...extensionApis));
						if (hasConnectionListeners) socket[kPassthroughPromise].resolve(false);
						else {
							socket[kPassthroughPromise].resolve(true);
							server.connect();
							server.addEventListener("open", () => {
								socket.dispatchEvent(bindEvent(socket, new Event("open")));
								if (server["realWebSocket"]) socket.protocol = server["realWebSocket"].protocol;
							});
						}
					} catch (error) {
						/**
						* @note Translate unhandled exceptions during the connection
						* handling (i.e. interceptor exceptions) as WebSocket connection
						* closures with error. This prevents from the exceptions occurring
						* in `queueMicrotask` from being process-wide and uncatchable.
						*/
						if (error instanceof Error) {
							socket.dispatchEvent(new Event("error"));
							if (socket.readyState !== WebSocket.CLOSING && socket.readyState !== WebSocket.CLOSED) socket[kClose](1011, error.message, false);
							console.error(error);
						}
					}
				});
				return socket;
			} });
			logger$2.verbose("patching global WebSocket...");
			this.subscriptions.push(patchesRegistry.applyPatch(globalThis, "WebSocket", () => WebSocketProxy));
			logger$2.verbose("global WebSocket patched: %s", globalThis.WebSocket.name);
		}
	};
	//#endregion
	//#region src/core/utils/internal/is-object.ts
	/**
	* Determines if the given value is an object.
	*/
	function isObject(value) {
		return value != null && typeof value === "object" && !Array.isArray(value);
	}
	//#endregion
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
	//#region src/core/utils/logging/colors.ts
	/**
	* Colors for logging the direction of intercepted events.
	*
	* @note A standalone module so consumers interested only in the
	* palette (e.g. `sse`, `msw/graphql` loggers) don't pull the entire
	* WebSocket logger into their graph.
	*/
	const colors = {
		system: "#3b82f6",
		outgoing: "#22c55e",
		incoming: "#ef4444",
		mocked: "#ff6a33"
	};
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
	//#region src/core/utils/internal/has-ref-counted.ts
	function hasRefCounted(value) {
		return isObject(value) && typeof Reflect.get(value, "ref") === "function" && typeof Reflect.get(value, "unref") === "function";
	}
	//#endregion
	//#region src/core/utils/internal/attach-sibling-handlers.ts
	const kSiblingHandlers = Symbol("kSiblingHandlers");
	const kIsSiblingHandler = Symbol("kIsSiblingHandler");
	function attachSiblingHandlers(owner, siblings) {
		invariant$1(getSiblingHandlers(owner).length === 0, "Failed to merge handlers: the owner \"%s\" handler is already merged", owner.kind);
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
	//#region src/ws/websocket-upgrade.ts
	const WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
	/**
	* Response resolver for the `upgrade` requests to the WebSocket protocol.
	* This requires a WebSocket handler to be present to fire.
	* @note This only affects Node.js as the `upgrade` request header is
	* forbidden and cannot be read in the browser. Consider using the
	* `WebSocket` API for establishing WebSocket connections in the browser.
	*/
	async function webSocketUpgrade({ request }) {
		const key = request.headers.get("sec-websocket-key");
		if (!key) return;
		const keyBytes = new TextEncoder().encode(key + WEBSOCKET_GUID);
		const digest = await crypto.subtle.digest("SHA-1", keyBytes);
		const acceptValue = btoa(String.fromCharCode(...new Uint8Array(digest)));
		const requestedProtocols = request.headers.get("sec-websocket-protocol")?.split(",").map((protocol) => protocol.trim());
		new WebSocket(resolveWebSocketUrl(request.url), requestedProtocols);
		const headers = new Headers({
			upgrade: "websocket",
			connection: "upgrade",
			"sec-websocket-accept": acceptValue
		});
		if (requestedProtocols && requestedProtocols.length > 0) headers.set("sec-websocket-protocol", requestedProtocols[0]);
		return new FetchResponse(null, {
			status: 101,
			headers
		});
	}
	/**
	* Creates a request handler that responds to WebSocket upgrade
	* requests whose URL matches the given path.
	*
	* @internal
	*/
	function createWebSocketUpgradeHandler(url, resolver) {
		return http.get(({ request }) => {
			return request.headers.get("upgrade")?.toLowerCase() === "websocket" && matchRequestUrl(new URL(resolveWebSocketUrl(request.url)), url).matches;
		}, resolver);
	}
	//#endregion
	//#region src/ws/websocket-memory-client-store.ts
	var WebSocketMemoryClientStore = class {
		store;
		constructor() {
			this.store = /* @__PURE__ */ new Map();
		}
		async add(client) {
			this.store.set(client.id, {
				id: client.id,
				url: client.url.href
			});
		}
		getAll() {
			return Promise.resolve(Array.from(this.store.values()));
		}
		async deleteMany(clientIds) {
			for (const clientId of clientIds) this.store.delete(clientId);
		}
	};
	//#endregion
	//#region src/ws/websocket-indexeddb-client-store.ts
	const DB_NAME = "msw-websocket-clients";
	const DB_STORE_NAME = "clients";
	var WebSocketIndexedDBClientStore = class {
		db;
		constructor() {
			this.db = this.createDatabase();
		}
		async add(client) {
			const promise = Promise.withResolvers();
			/**
			* @note Use `.put()` instead of `.add()` to allow setting clients
			* that already exist in the database. This can happen if a single page
			* has multiple event handlers. Each handler will receive the "connection"
			* event in parallel, and try to set that WebSocket client in the database.
			*/
			const request = (await this.getStore()).put({
				id: client.id,
				url: client.url.href
			});
			request.onsuccess = () => {
				promise.resolve();
			};
			request.onerror = () => {
				console.error(request.error);
				promise.reject(/* @__PURE__ */ new Error(`Failed to add WebSocket client "${client.id}". There is likely an additional output above.`));
			};
			return promise.promise;
		}
		async getAll() {
			const promise = Promise.withResolvers();
			const request = (await this.getStore()).getAll();
			request.onsuccess = () => {
				promise.resolve(request.result);
			};
			request.onerror = () => {
				console.error(request.error);
				promise.reject(/* @__PURE__ */ new Error(`Failed to get all WebSocket clients. There is likely an additional output above.`));
			};
			return promise.promise;
		}
		async deleteMany(clientIds) {
			const promise = Promise.withResolvers();
			const store = await this.getStore();
			for (const clientId of clientIds) store.delete(clientId);
			store.transaction.oncomplete = () => {
				promise.resolve();
			};
			store.transaction.onerror = () => {
				console.error(store.transaction.error);
				promise.reject(/* @__PURE__ */ new Error(`Failed to delete WebSocket clients [${clientIds.join(", ")}]. There is likely an additional output above.`));
			};
			return promise.promise;
		}
		async createDatabase() {
			const promise = Promise.withResolvers();
			const request = indexedDB.open(DB_NAME, 1);
			request.onsuccess = ({ currentTarget }) => {
				const db = Reflect.get(currentTarget, "result");
				if (db.objectStoreNames.contains(DB_STORE_NAME)) return promise.resolve(db);
			};
			request.onupgradeneeded = async ({ currentTarget }) => {
				const db = Reflect.get(currentTarget, "result");
				if (db.objectStoreNames.contains(DB_STORE_NAME)) return;
				const store = db.createObjectStore(DB_STORE_NAME, { keyPath: "id" });
				store.transaction.oncomplete = () => {
					promise.resolve(db);
				};
				store.transaction.onerror = () => {
					console.error(store.transaction.error);
					promise.reject(/* @__PURE__ */ new Error("Failed to create WebSocket client store. There is likely an additional output above."));
				};
			};
			request.onerror = () => {
				console.error(request.error);
				promise.reject(/* @__PURE__ */ new Error("Failed to open an IndexedDB database. There is likely an additional output above."));
			};
			return promise.promise;
		}
		async getStore() {
			return (await this.db).transaction(DB_STORE_NAME, "readwrite").objectStore(DB_STORE_NAME);
		}
	};
	//#endregion
	//#region src/ws/websocket-client-manager.ts
	/**
	* A manager responsible for accumulating WebSocket client
	* connections across different browser runtimes.
	*/
	var WebSocketClientManager = class {
		channel;
		store;
		runtimeClients;
		allClients;
		constructor(channel) {
			this.channel = channel;
			this.store = typeof indexedDB !== "undefined" ? new WebSocketIndexedDBClientStore() : new WebSocketMemoryClientStore();
			this.runtimeClients = /* @__PURE__ */ new Map();
			this.allClients = /* @__PURE__ */ new Set();
			this.channel.addEventListener("message", (message) => {
				if (message.data?.type === "db:update") this.flushDatabaseToMemory();
			});
			if (typeof window !== "undefined") window.addEventListener("message", async (message) => {
				if (message.data?.type === "msw/worker:stop") await this.removeRuntimeClients();
			});
		}
		async flushDatabaseToMemory() {
			const storedClients = await this.store.getAll();
			this.allClients = new Set(storedClients.map((client) => {
				const runtimeClient = this.runtimeClients.get(client.id);
				/**
				* @note For clients originating in this runtime, use their
				* direct references. No need to wrap them in a remote connection.
				*/
				if (runtimeClient) return runtimeClient;
				return new WebSocketRemoteClientConnection(client.id, new URL(client.url), this.channel);
			}));
		}
		async removeRuntimeClients() {
			await this.store.deleteMany(Array.from(this.runtimeClients.keys()));
			this.runtimeClients.clear();
			await this.flushDatabaseToMemory();
			this.notifyOthersAboutDatabaseUpdate();
		}
		/**
		* All active WebSocket client connections.
		*/
		get clients() {
			return this.allClients;
		}
		/**
		* Notify other runtimes about the database update
		* using the shared `BroadcastChannel` instance.
		*/
		notifyOthersAboutDatabaseUpdate() {
			this.channel.postMessage({ type: "db:update" });
		}
		async addClient(client) {
			await this.store.add(client);
			await this.flushDatabaseToMemory();
			this.notifyOthersAboutDatabaseUpdate();
		}
		/**
		* Adds the given `WebSocket` client connection to the set
		* of all connections. The given connection is always the complete
		* connection object because `addConnection()` is called only
		* for the opened connections in the same runtime.
		*/
		async addConnection(client) {
			this.runtimeClients.set(client.id, client);
			await this.addClient(client);
			const handleExtraneousMessage = (message) => {
				const { type, payload } = message.data;
				if (typeof payload === "object" && "clientId" in payload && payload.clientId !== client.id) return;
				switch (type) {
					case "extraneous:send":
						client.send(payload.data);
						break;
					case "extraneous:close": client.close(payload.code, payload.reason);
				}
			};
			const abortController = new AbortController();
			this.channel.addEventListener("message", handleExtraneousMessage, { signal: abortController.signal });
			client.addEventListener("close", () => abortController.abort(), { once: true });
		}
	};
	/**
	* A wrapper class to operate with WebSocket client connections
	* from other runtimes. This class maintains 1-1 public API
	* compatibility to the `WebSocketClientConnection` but relies
	* on the given `BroadcastChannel` to communicate instructions
	* with the client connections from other runtimes.
	*/
	var WebSocketRemoteClientConnection = class {
		id;
		url;
		channel;
		constructor(id, url, channel) {
			this.id = id;
			this.url = url;
			this.channel = channel;
		}
		send(data) {
			this.channel.postMessage({
				type: "extraneous:send",
				payload: {
					clientId: this.id,
					data
				}
			});
		}
		close(code, reason) {
			this.channel.postMessage({
				type: "extraneous:close",
				payload: {
					clientId: this.id,
					code,
					reason
				}
			});
		}
		addEventListener(_type, _listener, _options) {
			throw new Error("WebSocketRemoteClientConnection.addEventListener is not supported");
		}
		removeEventListener(_event, _listener, _options) {
			throw new Error("WebSocketRemoteClientConnection.removeEventListener is not supported");
		}
	};
	//#endregion
	//#region src/ws/ws.ts
	const webSocketChannel = new BroadcastChannel("msw:websocket-client-manager");
	if (hasRefCounted(webSocketChannel)) webSocketChannel.unref();
	/**
	* Intercepts outgoing WebSocket connections to the given URL.
	*
	* @example
	* const chat = ws.link('wss://chat.example.com')
	* chat.addEventListener('connection', ({ client }) => {
	*   client.send('hello from server!')
	* })
	*/
	function createWebSocketLinkHandler(url, options) {
		invariant$1(url, "Expected a WebSocket server URL but got undefined");
		invariant$1(isPath(url), "Expected a WebSocket server URL to be a valid path but got %s", typeof url);
		const clientManager = new WebSocketClientManager(webSocketChannel);
		const upgradeHandler = createWebSocketUpgradeHandler(url, (info) => {
			return ws.onUpgrade(info);
		});
		return {
			get clients() {
				return clientManager.clients;
			},
			addEventListener(event, listener) {
				const webSocketHandler = new WebSocketHandler(url, { extensions: options?.extensions });
				webSocketHandler[kEmitter].on("connection", async ({ client }) => {
					await clientManager.addConnection(client);
				});
				webSocketHandler[kEmitter].on(event, listener);
				return attachSiblingHandlers(webSocketHandler, [upgradeHandler]);
			},
			broadcast(data) {
				this.broadcastExcept([], data);
			},
			broadcastExcept(clients, data) {
				const ignoreClients = Array.prototype.concat(clients).map((client) => client.id);
				clientManager.clients.forEach((otherClient) => {
					if (!ignoreClients.includes(otherClient.id)) otherClient.send(data);
				});
			}
		};
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
	const ws = {
		link: createWebSocketLinkHandler,
		onUpgrade: webSocketUpgrade
	};
	//#endregion
	//#region src/utils/delay.ts
	const SET_TIMEOUT_MAX_ALLOWED_INT = 2147483647;
	const MIN_SERVER_RESPONSE_TIME = 100;
	const NODE_SERVER_RESPONSE_TIME = 5;
	function getRealisticResponseTime() {
		if (isNodeProcess()) return NODE_SERVER_RESPONSE_TIME;
		return Math.floor(Math.random() * 300 + MIN_SERVER_RESPONSE_TIME);
	}
	/**
	* Delays the response by the given duration (ms).
	*
	* @example
	* await delay() // emulate realistic server response time
	* await delay(1200) // delay response by 1200ms
	* await delay('infinite') // delay response infinitely
	*
	* @see {@link https://mswjs.io/docs/api/delay `delay()` API reference}
	*/
	async function delay(durationOrMode) {
		let delayTime;
		if (typeof durationOrMode === "string") switch (durationOrMode) {
			case "infinite":
				delayTime = SET_TIMEOUT_MAX_ALLOWED_INT;
				break;
			case "real":
				delayTime = getRealisticResponseTime();
				break;
			default: throw new Error(`Failed to delay a response: unknown delay mode "${durationOrMode}". Please make sure you provide one of the supported modes ("real", "infinite") or a number.`);
		}
		else if (typeof durationOrMode === "undefined") delayTime = getRealisticResponseTime();
		else {
			if (durationOrMode > SET_TIMEOUT_MAX_ALLOWED_INT) throw new Error(`Failed to delay a response: provided delay duration (${durationOrMode}) exceeds the maximum allowed duration for "setTimeout" (${SET_TIMEOUT_MAX_ALLOWED_INT}). This will cause the response to be returned immediately. Please use a number within the allowed range to delay the response by exact duration, or consider the "infinite" delay mode to delay the response indefinitely.`);
			delayTime = durationOrMode;
		}
		return new Promise((resolve) => {
			const timeoutId = setTimeout(resolve, delayTime);
			if (delayTime === SET_TIMEOUT_MAX_ALLOWED_INT && isNodeProcess() && hasRefCounted(timeoutId)) timeoutId.unref();
		});
	}
	//#endregion
	//#region src/sse/sse.ts
	/**
	* Intercept Server-Sent Events (SSE).
	*
	* @example
	* sse('http://localhost:4321', ({ client }) => {
	*   client.send({ data: 'hello world' })
	* })
	*
	* @see {@link https://mswjs.io/docs/sse/ Mocking Server-Sent Events}
	* @see {@link https://mswjs.io/docs/api/sse `sse()` API reference}
	*/
	const sse = (path, resolver) => {
		return new ServerSentEventHandler(path, resolver);
	};
	const SSE_RESPONSE_INIT = { headers: {
		"content-type": "text/event-stream",
		"cache-control": "no-cache",
		connection: "keep-alive"
	} };
	var ServerSentEventHandler = class extends HttpHandler {
		#loggableRequests;
		constructor(path, resolver) {
			invariant$1(typeof EventSource !== "undefined", "Failed to construct a Server-Sent Event handler for path \"%s\": the EventSource API is not supported in this environment", path);
			super("GET", path, async (info) => {
				const { client, server, response } = createEventStream(info.request);
				/**
				* @note Scope the emitter to this connection so its logging
				* listeners don't accumulate on the handler across connections.
				*/
				const emitter = new Emitter();
				client[kClientEmitter] = emitter;
				if (this.#loggableRequests.has(info.request)) this.#attachClientLogger(info.request, emitter);
				/**
				* @note Extend the resolver info via assignment instead of a spread.
				* Spreading the info would invoke its lazy `finalize` getter,
				* initializing the finalize machinery for resolvers that never use it.
				*/
				await resolver(Object.assign(info, {
					client,
					server
				}));
				return response;
			});
			this.#loggableRequests = /* @__PURE__ */ new WeakSet();
		}
		async predicate(args) {
			if (args.request.headers.get("accept") !== "text/event-stream") return false;
			const matches = await super.predicate(args);
			if (matches && !args.resolutionContext?.quiet) {
				/**
				* @note Log the intercepted request early.
				* Normally, the `this.log()` method is called when the handler returns a response.
				* For SSE, call that method earlier so the logs are in correct order.
				*/
				await super.log({
					request: args.request,
					/**
					* @note Construct a placeholder response since SSE response
					* is being streamed and cannot be cloned/consumed for logging.
					*/
					response: new Response("[streaming]", SSE_RESPONSE_INIT)
				});
				this.#loggableRequests.add(args.request);
			}
			return matches;
		}
		async log(args) {
			/**
			* @note Cancel the response stream because it's not needed for logging.
			* Otherwise, this cloned response remains unconsumed and its original
			* doesn't propagate stream cancelations at all.
			*/
			args.response.body?.cancel();
		}
		#attachClientLogger(request, emitter) {
			const publicUrl = toPublicUrl(request.url);
			emitter.on("message", ({ data }) => {
				console.groupCollapsed(devUtils.formatMessage(`${getTimestamp()} SSE %s %c⇣%c ${data.event}`), publicUrl, `color:${colors.mocked}`, "color:inherit");
				console.log(data.frames);
				console.groupEnd();
			});
			emitter.on("error", () => {
				console.groupCollapsed(devUtils.formatMessage(`${getTimestamp()} SSE %s %c\u00D7%c error`), publicUrl, `color: ${colors.system}`, "color:inherit");
				console.log("Handler:", this);
				console.groupEnd();
			});
			emitter.on("close", () => {
				console.groupCollapsed(devUtils.formatMessage(`${getTimestamp()} SSE %s %c■%c close`), publicUrl, `colors:${colors.system}`, "color:inherit");
				console.log("Handler:", this);
				console.groupEnd();
			});
		}
	};
	const kClientEmitter = Symbol.for("kClientEmitter");
	var ServerSentEventClient = class {
		[kClientEmitter];
		#encoder;
		#controller;
		#closed;
		#isClosed;
		constructor(controller) {
			this.#encoder = new TextEncoder();
			this.#controller = controller;
			this.#closed = Promise.withResolvers();
			this.#isClosed = false;
		}
		/**
		* Sends the given payload to the intercepted `EventSource`.
		*/
		send(payload) {
			if ("retry" in payload && payload.retry != null) {
				this.#sendRetry(payload.retry);
				return;
			}
			this.#sendMessage({
				id: payload.id,
				event: payload.event,
				data: typeof payload.data === "object" ? JSON.stringify(payload.data) : payload.data
			});
		}
		/**
		* Dispatches the given event on the intercepted `EventSource`.
		*/
		dispatchEvent(event) {
			if (event instanceof MessageEvent) {
				/**
				* @note Use the internal send mechanism to skip normalization
				* of the message data (already normalized by the server).
				*/
				this.#sendMessage({
					id: event.lastEventId || void 0,
					event: event.type === "message" ? void 0 : event.type,
					data: event.data
				});
				return;
			}
			if (event.type === "error") {
				this.error();
				return;
			}
			if (event.type === "close") {
				this.close();
				return;
			}
		}
		/**
		* Errors the underlying `EventSource`, closing the connection with an error.
		* This is equivalent to aborting the connection and will produce a `TypeError: Failed to fetch`
		* error.
		*/
		error() {
			if (this.#isClosed) return;
			this.#controller.error();
			this.#isClosed = true;
			this.#closed.resolve();
			this[kClientEmitter]?.emit(new TypedEvent("error"));
		}
		/**
		* Closes the underlying `EventSource`, closing the connection.
		*/
		close() {
			if (this.#isClosed) return;
			try {
				this.#controller.close();
				this.#isClosed = true;
				this.#closed.resolve();
			} catch {}
			this[kClientEmitter]?.emit(new TypedEvent("close"));
		}
		#enqueue(chunk) {
			if (this.#isClosed) return;
			try {
				this.#controller.enqueue(chunk);
			} catch (error) {
				console.error(error);
				devUtils.error("Failed to write to server-side EventSource. Please see the original error above.");
			}
		}
		#sendRetry(retry) {
			this.#enqueue(this.#encoder.encode(`retry:${retry}\n\n`));
		}
		#sendMessage(message) {
			const frames = [];
			if (message.id) frames.push(`id:${message.id}`);
			if (message.event) frames.push(`event:${message.event.toString()}`);
			if (message.data != null)
 /**
			* Split data on line terminators (LF, CR, or CRLF) and translate them to individual frames.
			* @see https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation
			* @see https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream
			*/
			for (const line of message.data.toString().split(/\r\n|\r|\n/)) frames.push(`data:${line}`);
			frames.push("", "");
			this.#enqueue(this.#encoder.encode(frames.join("\n")));
			this[kClientEmitter]?.emit(new TypedEvent("message", { data: {
				id: message.id,
				event: message.event?.toString() || "message",
				data: message.data,
				frames
			} }));
		}
	};
	var ServerSentEventServer = class {
		#request;
		#client;
		constructor(args) {
			this.#request = args.request;
			this.#client = args.client;
		}
		/**
		* Establishes the actual connection for this SSE request
		* and returns the `EventSource` instance.
		*/
		connect() {
			const source = new ObservableEventSource(this.#request.url, {
				withCredentials: this.#request.credentials === "include",
				headers: { 
				/**
				* @note Mark this request as passthrough so it doesn't trigger
				* an infinite loop matching against the existing request handler.
				*/
accept: "msw/passthrough" },
				signal: this.#request.signal
			});
			source[kOnAnyMessage] = (event) => {
				Object.defineProperties(event, { target: {
					value: this,
					enumerable: true,
					writable: true,
					configurable: true
				} });
				queueMicrotask(() => {
					if (!event.defaultPrevented) this.#client.dispatchEvent(event);
				});
			};
			source.addEventListener("error", (event) => {
				Object.defineProperties(event, { target: {
					value: this,
					enumerable: true,
					writable: true,
					configurable: true
				} });
				queueMicrotask(() => {
					if (!event.defaultPrevented) this.#client.dispatchEvent(event);
				});
			});
			return source;
		}
	};
	const kRequest = Symbol("kRequest");
	const kReconnectionTime = Symbol("kReconnectionTime");
	const kLastEventId = Symbol("kLastEventId");
	const kAbortController = Symbol("kAbortController");
	const kOnOpen = Symbol("kOnOpen");
	const kOnMessage = Symbol("kOnMessage");
	const kOnAnyMessage = Symbol("kOnAnyMessage");
	const kOnError = Symbol("kOnError");
	var ObservableEventSource = class ObservableEventSource extends EventTarget {
		static CONNECTING = 0;
		static OPEN = 1;
		static CLOSED = 2;
		CONNECTING = ObservableEventSource.CONNECTING;
		OPEN = ObservableEventSource.OPEN;
		CLOSED = ObservableEventSource.CLOSED;
		readyState;
		url;
		withCredentials;
		[kRequest];
		[kReconnectionTime];
		[kLastEventId];
		[kAbortController];
		[kOnOpen] = null;
		[kOnMessage] = null;
		[kOnAnyMessage] = null;
		[kOnError] = null;
		constructor(url, init) {
			super();
			this.url = new URL(url).href;
			this.withCredentials = init?.withCredentials ?? false;
			this.readyState = this.CONNECTING;
			const headers = new Headers(init?.headers || {});
			headers.append("accept", "text/event-stream");
			this[kAbortController] = new AbortController();
			this[kReconnectionTime] = 2e3;
			this[kLastEventId] = "";
			this[kRequest] = new Request(this.url, {
				method: "GET",
				headers,
				credentials: this.withCredentials ? "include" : "omit",
				signal: this[kAbortController].signal
			});
			if (init?.signal) {
				if (init.signal.aborted) {
					this.close();
					return;
				}
				init.signal.addEventListener("abort", () => this.close(), {
					once: true,
					signal: this[kAbortController].signal
				});
			}
			this.connect();
		}
		get onopen() {
			return this[kOnOpen];
		}
		set onopen(handler) {
			if (this[kOnOpen]) this.removeEventListener("open", this[kOnOpen]);
			this[kOnOpen] = handler.bind(this);
			this.addEventListener("open", this[kOnOpen]);
		}
		get onmessage() {
			return this[kOnMessage];
		}
		set onmessage(handler) {
			if (this[kOnMessage]) this.removeEventListener("message", { handleEvent: this[kOnMessage] });
			this[kOnMessage] = handler.bind(this);
			this.addEventListener("message", { handleEvent: this[kOnMessage] });
		}
		get onerror() {
			return this[kOnError];
		}
		set onerror(handler) {
			if (this[kOnError]) this.removeEventListener("error", { handleEvent: this[kOnError] });
			this[kOnError] = handler.bind(this);
			this.addEventListener("error", { handleEvent: this[kOnError] });
		}
		addEventListener(type, listener, options) {
			super.addEventListener(type, listener, options);
		}
		removeEventListener(type, listener, options) {
			super.removeEventListener(type, listener, options);
		}
		dispatchEvent(event) {
			return super.dispatchEvent(event);
		}
		close() {
			this[kAbortController].abort();
			this.readyState = this.CLOSED;
		}
		async connect() {
			await fetch(this[kRequest]).then((response) => {
				this.processResponse(response);
			}).catch(() => {
				this.failConnection();
			});
		}
		processResponse(response) {
			if (!response.body) {
				this.failConnection();
				return;
			}
			if (isNetworkError(response)) {
				this.reestablishConnection();
				return;
			}
			if (response.status !== 200 || response.headers.get("content-type") !== "text/event-stream") {
				this.failConnection();
				return;
			}
			this.announceConnection();
			this.interpretResponseBody(response);
		}
		announceConnection() {
			queueMicrotask(() => {
				if (this.readyState !== this.CLOSED) {
					this.readyState = this.OPEN;
					this.dispatchEvent(new Event("open"));
				}
			});
		}
		interpretResponseBody(response) {
			const parsingStream = new EventSourceParsingStream({
				message: (message) => {
					if (message.id) this[kLastEventId] = message.id;
					const messageEvent = new MessageEvent(message.event ? message.event : "message", {
						data: message.data,
						origin: this[kRequest].url,
						lastEventId: this[kLastEventId],
						cancelable: true
					});
					this[kOnAnyMessage]?.(messageEvent);
					this.dispatchEvent(messageEvent);
				},
				retry: (reconnectionTime) => {
					this[kReconnectionTime] = reconnectionTime;
				},
				abort: () => {
					throw new Error("Stream abort is not implemented");
				},
				close: () => {
					this.failConnection();
				}
			});
			response.body.pipeTo(parsingStream).then(() => {
				this.processResponseEndOfBody(response);
			}).catch(() => {
				this.failConnection();
			});
		}
		processResponseEndOfBody(response) {
			if (!isNetworkError(response)) this.reestablishConnection();
		}
		async reestablishConnection() {
			queueMicrotask(() => {
				if (this.readyState === this.CLOSED) return;
				this.readyState = this.CONNECTING;
				this.dispatchEvent(new Event("error"));
			});
			const signal = this[kAbortController].signal;
			if (signal.aborted) return;
			const aborted = Promise.withResolvers();
			const onAbort = () => aborted.resolve();
			signal.addEventListener("abort", onAbort, { once: true });
			await Promise.race([delay(this[kReconnectionTime]), aborted.promise]).finally(() => {
				signal.removeEventListener("abort", onAbort);
			});
			if (signal.aborted) return;
			queueMicrotask(async () => {
				if (this.readyState !== this.CONNECTING) return;
				if (this[kLastEventId] !== "") this[kRequest].headers.set("last-event-id", this[kLastEventId]);
				await this.connect();
			});
		}
		failConnection() {
			queueMicrotask(() => {
				if (this.readyState !== this.CLOSED) {
					this.readyState = this.CLOSED;
					this.dispatchEvent(new Event("error"));
				}
			});
		}
	};
	/**
	* Checks if the given `Response` instance is a network error.
	* @see https://fetch.spec.whatwg.org/#concept-network-error
	*/
	function isNetworkError(response) {
		return response.type === "error" && response.status === 0 && response.statusText === "" && Array.from(response.headers.entries()).length === 0 && response.body === null;
	}
	var EventSourceParsingStream = class extends WritableStream {
		underlyingSink;
		decoder;
		buffer;
		position;
		fieldLength;
		discardTrailingNewline = false;
		message = {
			id: void 0,
			event: void 0,
			data: void 0
		};
		constructor(underlyingSink) {
			super({
				write: (chunk) => {
					this.processResponseBodyChunk(chunk);
				},
				abort: (reason) => {
					this.underlyingSink.abort?.(reason);
				},
				close: () => {
					this.underlyingSink.close?.();
				}
			});
			this.underlyingSink = underlyingSink;
			this.decoder = new TextDecoder();
			this.position = 0;
		}
		resetMessage() {
			this.message = {
				id: void 0,
				event: void 0,
				data: void 0
			};
		}
		processResponseBodyChunk(chunk) {
			if (this.buffer == null) {
				this.buffer = chunk;
				this.position = 0;
				this.fieldLength = -1;
			} else {
				const nextBuffer = new Uint8Array(this.buffer.length + chunk.length);
				nextBuffer.set(this.buffer);
				nextBuffer.set(chunk, this.buffer.length);
				this.buffer = nextBuffer;
			}
			const bufferLength = this.buffer.length;
			let lineStart = 0;
			while (this.position < bufferLength) {
				if (this.discardTrailingNewline) {
					if (this.buffer[this.position] === 10) lineStart = ++this.position;
					this.discardTrailingNewline = false;
				}
				let lineEnd = -1;
				for (; this.position < bufferLength && lineEnd === -1; ++this.position) switch (this.buffer[this.position]) {
					case 58:
						if (this.fieldLength === -1) this.fieldLength = this.position - lineStart;
						break;
					case 13:
						this.discardTrailingNewline = true;
						break;
					case 10: lineEnd = this.position;
				}
				if (lineEnd === -1) break;
				this.processLine(this.buffer.subarray(lineStart, lineEnd), this.fieldLength);
				lineStart = this.position;
				this.fieldLength = -1;
			}
			if (lineStart === bufferLength) this.buffer = void 0;
			else if (lineStart !== 0) {
				this.buffer = this.buffer.subarray(lineStart);
				this.position -= lineStart;
			}
		}
		processLine(line, fieldLength) {
			if (line.length === 0) {
				if (this.message.data === void 0) {
					this.message.event = void 0;
					return;
				}
				this.underlyingSink.message(this.message);
				this.resetMessage();
				return;
			}
			if (fieldLength > 0) {
				const field = this.decoder.decode(line.subarray(0, fieldLength));
				const valueOffset = fieldLength + (line[fieldLength + 1] === 32 ? 2 : 1);
				const value = this.decoder.decode(line.subarray(valueOffset));
				switch (field) {
					case "data":
						this.message.data = this.message.data ? this.message.data + "\n" + value : value;
						break;
					case "event":
						this.message.event = value;
						break;
					case "id":
						this.message.id = value;
						break;
					case "retry":
 /**
					* Apply the retry immediately. Don't buffer onto the current message.
					* @see https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation
					*/
					if (/^\d+$/.test(value)) this.underlyingSink.retry?.(parseInt(value, 10));
				}
			}
		}
	};
	/**
	* Create an event stream out of the given Fetch API `Request`.
	* Returns the following properties:
	* - `client`, to operate on the intercepted request;
	* - `server`, to establish and manage the actual server connection;
	* - `response`, a `Response` to use as the mock response's body.
	*
	* @example
	* http.post('/resource', ({ request }) => {
	*   const { client, server, response } = createEventStream(request)
	*   client.send({ data: 'hello world' })
	*   return response
	* })
	*/
	function createEventStream(request) {
		invariant$1(!request.signal.aborted, "Failed to call \"createEventStream\" on the \"%s %s\" request: request aborted", request.method, request.url);
		let controller;
		const readable = new ReadableStream({
			start(defaultController) {
				controller = defaultController;
			},
			cancel() {
				client.close();
			}
		});
		const client = new ServerSentEventClient(controller);
		const server = new ServerSentEventServer({
			request,
			client
		});
		const response = new Response(readable, SSE_RESPONSE_INIT);
		request.signal.addEventListener("abort", () => {
			client.close();
		}, { once: true });
		return {
			client,
			server,
			response
		};
	}
	//#endregion
	//#region src/core/utils/execute-handlers.ts
	/**
	* Executes the list of request handlers against the given request.
	* Returns the execution result object containing any matching request
	* handler and any mocked response it returned.
	*/
	const executeHandlers = async ({ request, requestId, handlers, resolutionContext }) => {
		let matchingHandler = null;
		let result = null;
		for (const handler of handlers) {
			result = await handler.run({
				request,
				requestId,
				resolutionContext
			});
			if (result !== null) matchingHandler = handler;
			if (result?.response) break;
		}
		if (matchingHandler) return {
			handler: matchingHandler,
			parsedResult: result?.parsedResult,
			response: result?.response
		};
		return null;
	};
	//#endregion
	//#region src/utils/get-response.ts
	/**
	* Finds a response for the given request instance
	* in the array of request handlers.
	* @param handlers The array of request handlers.
	* @param request The `Request` instance.
	* @param resolutionContext Request resolution options.
	* @returns {Response} A mocked response, if any.
	*/
	const getResponse = async (handlers, request, resolutionContext) => {
		return (await executeHandlers({
			request,
			requestId: createRequestId(),
			handlers,
			resolutionContext
		}))?.response;
	};
	//#endregion
	//#region src/http/symbols.ts
	/**
	* Symbols of the `msw/http` module.
	*
	* @note A standalone module so consumers interested only in a symbol
	* (e.g. `msw/graphql`) don't pull the modules that use it into
	* their graph.
	*/
	/**
	* Marks a response whose `Content-Type` header was inferred by the
	* library instead of being set explicitly by the developer.
	*/
	const kDefaultContentType = Symbol.for("kDefaultContentType");
	/**
	* Associates the mocked response body type with the response instance
	* for stricter typing of the response resolvers.
	*/
	const bodyType = Symbol("bodyType");
	//#endregion
	//#region src/http/http-response.ts
	/**
	* A drop-in replacement for the standard `Response` class
	* to allow additional features, like mocking the response `Set-Cookie` header.
	*
	* @example
	* new HttpResponse('Hello world', { status: 201 })
	* HttpResponse.json({ name: 'John' })
	* HttpResponse.formData(form)
	*
	* @see {@link https://mswjs.io/docs/api/http-response `HttpResponse` API reference}
	*/
	var HttpResponse = class HttpResponse extends FetchResponse {
		[bodyType] = null;
		constructor(body, init) {
			const responseInit = normalizeResponseInit(init);
			super(body, responseInit);
			decorateResponse(this, responseInit);
		}
		static error() {
			return super.error();
		}
		/**
		* Create a `Response` with a `Content-Type: "text/plain"` body.
		* @example
		* HttpResponse.text('hello world')
		* HttpResponse.text('Error', { status: 500 })
		*/
		static text(body, init) {
			const responseInit = normalizeResponseInit(init);
			const hasExplicitContentType = responseInit.headers.has("Content-Type");
			if (!hasExplicitContentType) responseInit.headers.set("Content-Type", "text/plain");
			if (!responseInit.headers.has("Content-Length")) responseInit.headers.set("Content-Length", body ? new Blob([body]).size.toString() : "0");
			const response = new HttpResponse(body, responseInit);
			if (!hasExplicitContentType) Object.defineProperty(response, kDefaultContentType, {
				value: true,
				enumerable: false
			});
			return response;
		}
		/**
		* Create a `Response` with a `Content-Type: "application/json"` body.
		* @example
		* HttpResponse.json({ firstName: 'John' })
		* HttpResponse.json({ error: 'Not Authorized' }, { status: 401 })
		*/
		static json(body, init) {
			const responseInit = normalizeResponseInit(init);
			const hasExplicitContentType = responseInit.headers.has("Content-Type");
			if (!hasExplicitContentType) responseInit.headers.set("Content-Type", "application/json");
			/**
			* @note TypeScript is incorrect here.
			* Stringifying undefined will return undefined.
			*/
			const responseText = JSON.stringify(body);
			if (!responseInit.headers.has("Content-Length")) responseInit.headers.set("Content-Length", responseText ? new Blob([responseText]).size.toString() : "0");
			const response = new HttpResponse(responseText, responseInit);
			if (!hasExplicitContentType) Object.defineProperty(response, kDefaultContentType, {
				value: true,
				enumerable: false
			});
			return response;
		}
		/**
		* Create a `Response` with a `Content-Type: "application/xml"` body.
		* @example
		* HttpResponse.xml(`<user name="John" />`)
		* HttpResponse.xml(`<article id="abc-123" />`, { status: 201 })
		*/
		static xml(body, init) {
			const responseInit = normalizeResponseInit(init);
			const hasExplicitContentType = responseInit.headers.has("Content-Type");
			if (!hasExplicitContentType) responseInit.headers.set("Content-Type", "text/xml");
			const response = new HttpResponse(body, responseInit);
			if (!hasExplicitContentType) Object.defineProperty(response, kDefaultContentType, {
				value: true,
				enumerable: false
			});
			return response;
		}
		/**
		* Create a `Response` with a `Content-Type: "text/html"` body.
		* @example
		* HttpResponse.html(`<p class="author">Jane Doe</p>`)
		* HttpResponse.html(`<main id="abc-123">Main text</main>`, { status: 201 })
		*/
		static html(body, init) {
			const responseInit = normalizeResponseInit(init);
			const hasExplicitContentType = responseInit.headers.has("Content-Type");
			if (!hasExplicitContentType) responseInit.headers.set("Content-Type", "text/html");
			const response = new HttpResponse(body, responseInit);
			if (!hasExplicitContentType) Object.defineProperty(response, kDefaultContentType, {
				value: true,
				enumerable: false
			});
			return response;
		}
		/**
		* Create a `Response` with an `ArrayBuffer` body.
		* @example
		* const buffer = new ArrayBuffer(3)
		* const view = new Uint8Array(buffer)
		* view.set([1, 2, 3])
		*
		* HttpResponse.arrayBuffer(buffer)
		*/
		static arrayBuffer(body, init) {
			const responseInit = normalizeResponseInit(init);
			const hasExplicitContentType = responseInit.headers.has("Content-Type");
			if (!hasExplicitContentType) responseInit.headers.set("Content-Type", "application/octet-stream");
			if (body && !responseInit.headers.has("Content-Length")) responseInit.headers.set("Content-Length", body.byteLength.toString());
			const response = new HttpResponse(body, responseInit);
			if (!hasExplicitContentType) Object.defineProperty(response, kDefaultContentType, {
				value: true,
				enumerable: false
			});
			return response;
		}
		/**
		* Create a `Response` with a `FormData` body.
		* @example
		* const data = new FormData()
		* data.set('name', 'Alice')
		*
		* HttpResponse.formData(data)
		*/
		static formData(body, init) {
			return new HttpResponse(body, normalizeResponseInit(init));
		}
	};
	//#endregion
	//#region src/utils/bypass.ts
	/**
	* Creates a `Request` instance that will always be ignored by MSW.
	*
	* @example
	* import { bypass } from 'msw'
	*
	* fetch(bypass('/resource'))
	* fetch(bypass(new URL('/resource', 'https://example.com)))
	* fetch(bypass(new Request('https://example.com/resource')))
	*
	* @see {@link https://mswjs.io/docs/api/bypass `bypass()` API reference}
	*/
	function bypass(input, init) {
		const request = new Request(input instanceof Request ? input.clone() : input, init);
		invariant$1(!request.bodyUsed, "Failed to create a bypassed request to \"%s %s\": given request instance already has its body read. Make sure to clone the intercepted request if you wish to read its body before bypassing it.", request.method, request.url);
		const requestClone = request.clone();
		/**
		* Send the internal request header that would instruct MSW
		* to perform this request as-is, ignoring any matching handlers.
		* @note Use the `accept` header to support scenarios when the
		* request cannot have headers (e.g. `sendBeacon` requests).
		*/
		requestClone.headers.append("accept", "msw/passthrough");
		/**
		* Delete the "content-length" request header.
		* Intercepted requests are parsed from the wire and include the
		* received "content-length" header. If the consumer derives a new
		* request with a different body (e.g. `new Request(request, { body })`),
		* that header becomes stale and the request client will reject the
		* bypassed request due to the content length mismatch. The request
		* client always re-computes this header from the actual request body.
		*/
		requestClone.headers.delete("content-length");
		return requestClone;
	}
	//#endregion
	//#region src/utils/passthrough.ts
	const REQUEST_INTENTION_HEADER_NAME = "x-msw-intention";
	/**
	* Performs the intercepted request as-is.
	*
	* This stops request handler lookup so no other handlers
	* can affect this request past this point.
	* Unlike `bypass()`, this will not trigger an additional request.
	*
	* @example
	* http.get('/resource', () => {
	*   return passthrough()
	* })
	*
	* @see {@link https://mswjs.io/docs/api/passthrough `passthrough()` API reference}
	*/
	function passthrough() {
		return new Response(null, {
			status: 302,
			statusText: "Passthrough",
			headers: { [REQUEST_INTENTION_HEADER_NAME]: "passthrough" }
		});
	}
	/**
	* Returns `true` if the given response was created by `passthrough()`.
	*
	* @example
	* const response = passthrough()
	* isPassthroughResponse(response) // true
	*/
	function isPassthroughResponse(response) {
		return response.status === 302 && response.headers.get("x-msw-intention") === "passthrough";
	}
	//#endregion
	//#region src/utils/is-common-asset-request.ts
	/**
	* Determines if the given request is a static asset request.
	* Useful when deciding which unhandled requests to ignore.
	* @note Despite being ignored, you can still intercept and mock
	* static assets by creating request handlers for them.
	*
	* @example
	* import { isCommonAssetRequest } from 'msw'
	* import { HttpNetworkFrame } from 'msw/experimental'
	*
	* await worker.start({
	*   onUnhandledFrame({ frame, defaults }) {
	*     if (frame instanceof HttpNetworkFrame && !isCommonAssetRequest(frame.data.request)) {
	*       defaults.warn()
	*     }
	*   }
	* })
	*/
	function isCommonAssetRequest(request) {
		const url = new URL(request.url);
		if (url.protocol === "file:") return true;
		if (/(fonts\.googleapis\.com)/.test(url.hostname)) return true;
		if (/node_modules/.test(url.pathname)) return true;
		if (url.pathname.includes("@vite")) return true;
		return /\.(s?css|less|m?jsx?|m?tsx?|html|ttf|otf|woff|woff2|eot|gif|jpe?g|png|avif|webp|svg|mp4|webm|ogg|mov|mp3|wav|ogg|flac|aac|pdf|txt|csv|json|xml|md|zip|tar|gz|rar|7z)$/i.test(url.pathname);
	}
	//#endregion
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
			invariant$1(this.#validateHandlers(initialHandlers), devUtils.formatMessage("Failed to apply given request handlers: invalid input. Did you forget to spread the request handlers Array?"));
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
			invariant$1(this.#validateHandlers(nextHandlers), devUtils.formatMessage("[MSW] Failed to call \"use()\" with the given request handlers: invalid input. Did you forget to spread the array of request handlers?"));
			if (nextHandlers.length === 0) return;
			const { handlers } = this.getState();
			const overrides = groupHandlersByKind(nextHandlers);
			if (overrides.request) prependHandlersToGroup(handlers, "request", overrides.request);
			if (overrides.websocket) prependHandlersToGroup(handlers, "websocket", overrides.websocket);
			this.setState({ handlers });
		}
		reset(nextHandlers) {
			invariant$1(nextHandlers.length > 0 ? this.#validateHandlers(nextHandlers) : true, devUtils.formatMessage("Failed to replace initial handlers during reset: invalid handlers. Did you forget to spread the handlers array?"));
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
				invariant$1(readyState === 0, "Failed to call \"configure()\" on the network: cannot configure an already enabled network.");
				if (options.handlers && !Object.is(options.handlers, resolvedOptions.handlers)) handlersController = deriveHandlersController(options.handlers);
				resolvedOptions = {
					...resolvedOptions,
					...options
				};
			},
			enable() {
				invariant$1(readyState === 0, "Failed to call \"enable\" on the network: already enabled");
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
				invariant$1(readyState === 1, "Failed to call \"disable\" on the network: already disabled");
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
	//#region node_modules/.pnpm/until-async@3.0.2/node_modules/until-async/lib/index.js
	/**
	* Gracefully handles a callback that returns a promise.
	*
	* @example
	* await until(() => Promise.resolve(123))
	* // [null, 123]
	*
	* await until(() => Promise.reject(new Error('Oops!')))
	* // [new Error('Oops!'), null]
	*/
	async function until$1(callback) {
		try {
			return [null, await callback().catch((error) => {
				throw error;
			})];
		} catch (error) {
			return [error, null];
		}
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
			invariant$1.as(InternalError, strategy === "bypass" || strategy === "warn" || strategy === "error", devUtils.formatMessage("Failed to react to an unhandled network frame: unknown strategy \"%s\". Please provide one of the supported strategies (\"bypass\", \"warn\", \"error\") or a custom callback function as the value of the \"onUnhandledFrame\" option.", strategy));
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
			const [lookupError, lookupResult] = await until$1(() => {
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
	var WebSocketConnectionEvent$1 = class extends TypedEvent {
		url;
		protocols;
		constructor(type, data) {
			super(...[type, {}]);
			this.url = data.url;
			this.protocols = data.protocols;
		}
	};
	var WebSocketErrorEvent = class extends WebSocketConnectionEvent$1 {
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
			this.events.emit(new WebSocketConnectionEvent$1("websocket:connection", {
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
		const [registrationError, registrationResult] = await until$1(async () => {
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
			invariant$1(SUPPORTS_SERVICE_WORKER, "Failed to open a WorkerChannel: Service Worker is not supported in this environment.");
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
			invariant$1(SUPPORTS_SERVICE_WORKER, "Failed to post message on a WorkerChannel: the Service Worker API is unavailable in this environment. This is likely an issue with MSW. Please report it on GitHub: https://github.com/mswjs/msw/issues");
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
			invariant$1(supportsServiceWorker(), "Failed to use Service Worker as the network source: the Service Worker API is not supported in this environment");
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
			invariant$1(this.#clientPromise != null, "[ServiceWorkerSource] Failed to print a start message: client confirmation not received");
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
	//#region node_modules/.pnpm/@open-draft+until@3.0.1/node_modules/@open-draft/until/lib/index.js
	/**
	* Gracefully handles a callback that returns a promise.
	*
	* @example
	* await until(() => Promise.resolve(123))
	* // [null, 123]
	*
	* await until(() => Promise.reject(new Error('Oops!')))
	* // [new Error('Oops!'), null]
	*/
	async function until(callback) {
		try {
			return [null, await callback().catch((error) => {
				throw error;
			})];
		} catch (error) {
			return [error, null];
		}
	}
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/handle-request-y7ajyve5.js
	var HttpRequestEvent = class extends TypedEvent {
		constructor(data) {
			super(...["request", {}]);
			this.request = data.request;
			this.requestId = data.requestId;
			this.initiator = data.initiator;
			this.controller = data.controller;
		}
	};
	var HttpResponseEvent = class extends TypedEvent {
		constructor(data) {
			super(...["response", {}]);
			this.response = data.response;
			this.responseType = data.responseType;
			this.request = data.request;
			this.requestId = data.requestId;
			this.initiator = data.initiator;
		}
	};
	var UnhandledHttpException = class extends TypedEvent {
		constructor(data) {
			super(...["unhandledException", {}]);
			this.error = data.error;
			this.request = data.request;
			this.requestId = data.requestId;
			this.initiator = data.initiator;
			this.controller = data.controller;
		}
	};
	function isNodeLikeError(error) {
		if (error == null) return false;
		if (!(error instanceof Error)) return false;
		return "code" in error && "errno" in error;
	}
	async function handleRequest(options) {
		if (options.logger?.isEnabled("default")) formatRequest(options.request).then((message) => {
			options.logger?.info("[%s] %s", options.requestId, message);
		});
		const handleResponse = async (response) => {
			if (response instanceof Error) {
				await options.controller.errorWith(response);
				return true;
			}
			if (isResponseError(response)) {
				await options.controller.respondWith(response);
				return true;
			}
			/**
			* Handle normal responses or response-like objects.
			* @note This must come before the arbitrary object check
			* since Response instances are, in fact, objects.
			*/
			if (isResponseLike(response)) {
				await options.controller.respondWith(response);
				return true;
			}
			if (isObject$2(response)) {
				await options.controller.errorWith(response);
				return true;
			}
			return false;
		};
		const handleResponseError = async (error) => {
			if (error instanceof InterceptorError) throw resultError;
			if (isNodeLikeError(error)) {
				await options.controller.errorWith(error);
				return true;
			}
			if (error instanceof Response) return await handleResponse(error);
			return false;
		};
		const requestAbortPromise = Promise.withResolvers();
		let requestAbortReason;
		let isRequestAborted = false;
		const onAbort = () => {
			isRequestAborted = true;
			requestAbortReason = options.request.signal?.reason;
			requestAbortPromise.reject(requestAbortReason);
		};
		/**
		* @note `signal` is not always defined in React Native.
		*/
		if (options.request.signal) {
			if (options.request.signal.aborted) {
				await options.controller.errorWith(options.request.signal.reason);
				return;
			}
			options.request.signal.addEventListener("abort", onAbort, { once: true });
		}
		const [resultError] = await until(async () => {
			const requestEvent = new HttpRequestEvent({
				initiator: options.initiator,
				requestId: options.requestId,
				request: options.request,
				controller: options.controller
			});
			const requestListenersPromise = options.emitter.emitAsPromise(requestEvent);
			await Promise.race([
				requestAbortPromise.promise,
				requestListenersPromise,
				options.controller.handled
			]);
			/**
			* @note If the "request" listener has replaced the request instance,
			* propagate that mutation back to the underlying insterceptor.
			* This happens with XMLHttpRequest that replaces request instances
			* to correctly reflect the "withCredentials" option on the Fetch API request.
			*/
			if (requestEvent.request !== options.request) options.request = requestEvent.request;
		});
		options.request.signal?.removeEventListener("abort", onAbort);
		if (isRequestAborted) {
			await options.controller.errorWith(requestAbortReason);
			return;
		}
		if (resultError) {
			if (await handleResponseError(resultError)) return;
			if (options.emitter.listenerCount("unhandledException") > 0) {
				const unhandledExceptionController = new RequestController(options.request, {
					/**
					* @note Intentionally empty passthrough handle.
					* This controller is created within another controller and we only need
					* to know if `unhandledException` listeners handled the request.
					*/
					passthrough() {},
					async respondWith(response) {
						await handleResponse(response);
					},
					async errorWith(reason) {
						/**
						* @note Handle the result of the unhandled controller
						* in the same way as the original request controller.
						* The exception here is that thrown errors within the
						* "unhandledException" event do NOT result in another
						* emit of the same event. They are forwarded as-is.
						*/
						await options.controller.errorWith(reason);
					}
				});
				await options.emitter.emitAsPromise(new UnhandledHttpException({
					initiator: options.initiator,
					error: resultError,
					request: options.request,
					requestId: options.requestId,
					controller: unhandledExceptionController
				}));
				if (unhandledExceptionController.readyState !== RequestController.PENDING) return;
			}
			await options.controller.respondWith(createServerErrorResponse(resultError));
			return;
		}
		if (options.controller.readyState === RequestController.PENDING) return await options.controller.passthrough();
		return options.controller.handled;
	}
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/web-CCLERSZF.js
	function createNetworkError(cause) {
		return Object.assign(/* @__PURE__ */ new TypeError("Failed to fetch"), { cause });
	}
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
	var BrotliDecompressionStream = class extends TransformStream {
		constructor() {
			console.warn("[Interceptors]: Brotli decompression of response streams is not supported in the browser");
			super({ transform(chunk, controller) {
				controller.enqueue(chunk);
			} });
		}
	};
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
		invariant$1(isCompressedResponse(response), "Failed to decompress a response: expected a response with a body and a non-empty \"content-encoding\" header");
		const decompressionStream = createDecompressionStream(response.headers.get("content-encoding"));
		response.body.pipeTo(decompressionStream.writable);
		return decompressionStream.readable;
	}
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
		const wrappedResponse = new FetchResponse(new ReadableStream({
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
		}, { highWaterMark: 0 }), response);
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
	const logger$1 = createLogger("fetch");
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
			logger$1.verbose("patching global fetch...");
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
							logger$1.verbose("performing request as-is");
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
							logger$1.verbose("original fetch performed %o", originalResponse);
							if (this.emitter.listenerCount("response") > 0) {
								logger$1.verbose("emitting the \"response\" event");
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
								logger$1.verbose("request errored %o", { response: rawResponse });
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
								logger$1.verbose("emitting the \"response\" event");
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
							logger$1.verbose("request aborted %o", { reason });
							responsePromise.reject(reason);
						}
					}, {
						logger: logger$1,
						requestId
					});
					logger$1.verbose("awaiting request resolution");
					logger$1.verbose("emitting the \"request\" event for %s listener(s)...", this.emitter.listenerCount("request"));
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
						logger: logger$1
					});
					return responsePromise.promise;
				};
			}));
			logger$1.verbose("global fetch patched: %s", globalThis.fetch.name);
		}
	};
	//#endregion
	//#region node_modules/.pnpm/@mswjs+interceptors@0.45.6_supports-color@8.1.1/node_modules/@mswjs/interceptors/lib/browser/web-BRBQ3YPp.js
	/**
	* Concatenate two `Uint8Array` buffers.
	*/
	function concatArrayBuffer(left, right) {
		const result = new Uint8Array(left.byteLength + right.byteLength);
		result.set(left, 0);
		result.set(right, left.byteLength);
		return result;
	}
	var EventPolyfill = class {
		constructor(type, options) {
			this.NONE = 0;
			this.CAPTURING_PHASE = 1;
			this.AT_TARGET = 2;
			this.BUBBLING_PHASE = 3;
			this.type = "";
			this.srcElement = null;
			this.currentTarget = null;
			this.eventPhase = 0;
			this.isTrusted = true;
			this.composed = false;
			this.cancelable = true;
			this.defaultPrevented = false;
			this.bubbles = true;
			this.lengthComputable = true;
			this.loaded = 0;
			this.total = 0;
			this.cancelBubble = false;
			this.returnValue = true;
			this.type = type;
			this.target = options?.target || null;
			this.currentTarget = options?.currentTarget || null;
			this.timeStamp = Date.now();
		}
		composedPath() {
			return [];
		}
		initEvent(type, bubbles, cancelable) {
			this.type = type;
			this.bubbles = !!bubbles;
			this.cancelable = !!cancelable;
		}
		preventDefault() {
			this.defaultPrevented = true;
		}
		stopPropagation() {}
		stopImmediatePropagation() {}
	};
	var ProgressEventPolyfill = class extends EventPolyfill {
		constructor(type, init) {
			super(type);
			this.lengthComputable = init?.lengthComputable || false;
			this.composed = init?.composed || false;
			this.loaded = init?.loaded || 0;
			this.total = init?.total || 0;
		}
	};
	const SUPPORTS_PROGRESS_EVENT = typeof ProgressEvent !== "undefined";
	function createEvent(target, type, init) {
		const progressEvents = [
			"error",
			"progress",
			"loadstart",
			"loadend",
			"load",
			"timeout",
			"abort"
		];
		/**
		* `ProgressEvent` is not supported in React Native.
		* @see https://github.com/mswjs/interceptors/issues/40
		*/
		const ProgressEventClass = SUPPORTS_PROGRESS_EVENT ? ProgressEvent : ProgressEventPolyfill;
		return progressEvents.includes(type) ? new ProgressEventClass(type, {
			lengthComputable: true,
			loaded: init?.loaded || 0,
			total: init?.total || 0
		}) : new EventPolyfill(type, {
			target,
			currentTarget: target
		});
	}
	/**
	* Returns the source object of the given property on the target object
	* (the target itself, any parent in its prototype, or null).
	*/
	function findPropertySource(target, propertyName) {
		if (!(propertyName in target)) return null;
		if (Object.prototype.hasOwnProperty.call(target, propertyName)) return target;
		const prototype = Reflect.getPrototypeOf(target);
		return prototype ? findPropertySource(prototype, propertyName) : null;
	}
	function createProxy(target, options) {
		return new Proxy(target, optionsToProxyHandler(options));
	}
	function optionsToProxyHandler(options) {
		const { constructorCall, methodCall, getProperty, setProperty } = options;
		const handler = {};
		if (typeof constructorCall !== "undefined") handler.construct = function(target, args, newTarget) {
			const next = Reflect.construct.bind(null, target, args, newTarget);
			return constructorCall.call(newTarget, args, next);
		};
		handler.set = function(target, propertyName, nextValue) {
			const next = () => {
				const propertySource = findPropertySource(target, propertyName) || target;
				const ownDescriptors = Reflect.getOwnPropertyDescriptor(propertySource, propertyName);
				if (typeof ownDescriptors?.set !== "undefined") {
					ownDescriptors.set.apply(target, [nextValue]);
					return true;
				}
				return Reflect.defineProperty(propertySource, propertyName, {
					writable: true,
					enumerable: true,
					configurable: true,
					value: nextValue
				});
			};
			if (typeof setProperty !== "undefined") return setProperty.call(target, [propertyName, nextValue], next);
			return next();
		};
		handler.get = function(target, propertyName, receiver) {
			/**
			* @note Using `Reflect.get()` here causes "TypeError: Illegal invocation".
			*/
			const next = () => target[propertyName];
			const value = typeof getProperty !== "undefined" ? getProperty.call(target, [propertyName, receiver], next) : next();
			if (typeof value === "function") return (...args) => {
				const next = value.bind(target, ...args);
				if (typeof methodCall !== "undefined") return methodCall.call(target, [propertyName, args], next);
				return next();
			};
			return value;
		};
		return handler;
	}
	function isDomParserSupportedType(type) {
		return [
			"application/xhtml+xml",
			"application/xml",
			"image/svg+xml",
			"text/html",
			"text/xml"
		].some((supportedType) => {
			return type.startsWith(supportedType);
		});
	}
	/**
	* Parses a given string into JSON.
	* Gracefully handles invalid JSON by returning `null`.
	*/
	function parseJson(data) {
		try {
			return JSON.parse(data);
		} catch (_) {
			return null;
		}
	}
	/**
	* Creates a Fetch API `Response` instance from the given
	* `XMLHttpRequest` instance and a response body.
	*/
	function createResponse(request, body) {
		return new FetchResponse(FetchResponse.isResponseWithBody(request.status) ? body : null, {
			url: request.responseURL,
			status: request.status,
			statusText: request.statusText,
			headers: createHeadersFromXMLHttpRequestHeaders(request.getAllResponseHeaders())
		});
	}
	function createHeadersFromXMLHttpRequestHeaders(headersString) {
		const headers = new Headers();
		const lines = headersString.split(/[\r\n]+/);
		for (const line of lines) {
			if (line.trim() === "") continue;
			const [name, ...parts] = line.split(": ");
			const value = parts.join(": ");
			headers.append(name, value);
		}
		return headers;
	}
	/**
	* Return a total byte length of the given request/response body.
	* If the `Content-Length` header is present, it will be used as the byte length.
	*/
	async function getBodyByteLength(input) {
		const explicitContentLength = input.headers.get("content-length");
		if (explicitContentLength != null && explicitContentLength !== "") return Number(explicitContentLength);
		return (await input.arrayBuffer()).byteLength;
	}
	const kIsRequestHandled = Symbol("kIsRequestHandled");
	const kFetchRequest = Symbol("kFetchRequest");
	const MAX_REDIRECTS = 20;
	/**
	* An `XMLHttpRequest` instance controller that allows us
	* to handle any given request instance (e.g. responding to it).
	*/
	var XMLHttpRequestController = class {
		constructor(initialRequest, logger) {
			this.initialRequest = initialRequest;
			this.logger = logger;
			this.sync = false;
			this.method = "GET";
			this.url = null;
			this[kIsRequestHandled] = false;
			this.redirectCount = 0;
			this.events = /* @__PURE__ */ new Map();
			this.uploadEvents = /* @__PURE__ */ new Map();
			this.requestId = createRequestId();
			this.requestHeaders = new Headers();
			this.responseBuffer = /* @__PURE__ */ new Uint8Array();
			this.request = createProxy(initialRequest, { methodCall: ([methodName, args], invoke) => {
				switch (methodName) {
					case "open": {
						const [method, url, async] = args;
						this.sync = !(async ?? true);
						if (typeof url === "undefined") {
							this.method = "GET";
							this.url = toAbsoluteUrl(method);
						} else {
							this.method = method;
							this.url = toAbsoluteUrl(url);
						}
						this.logger.verbose("open %s %s", this.method, this.url.href);
						return invoke();
					}
					case "addEventListener": {
						const [eventName, listener] = args;
						this.registerEvent(eventName, listener);
						this.logger.verbose("addEventListener", eventName, listener);
						return invoke();
					}
					case "setRequestHeader": {
						const [name, value] = args;
						this.requestHeaders.set(name, value);
						this.logger.verbose("setRequestHeader", name, value);
						return invoke();
					}
					case "send": {
						const [body] = args;
						if (this.sync) {
							console.warn(`Failed to intercept an XMLHttpRequest (${this.method} ${this.url}): synchronous requests are not supported. This request will be performed as-is.`);
							return invoke();
						}
						this.request.addEventListener("load", () => {
							if (typeof this.onResponse !== "undefined") {
								const fetchResponse = createResponse(
									this.request,
									/**
									* The `response` property is the right way to read
									* the ambiguous response body, as the request's "responseType" may differ.
									* @see https://xhr.spec.whatwg.org/#the-response-attribute
									*/
									this.request.response
								);
								this.onResponse.call(this, {
									response: fetchResponse,
									responseType: this[kIsRequestHandled] ? "mock" : "original",
									request: fetchRequest,
									requestId: this.requestId
								});
							}
						});
						const requestBody = typeof body === "string" ? encodeBuffer(body) : body;
						const fetchRequest = this.toFetchApiRequest(requestBody);
						this[kFetchRequest] = fetchRequest.clone();
						/**
						* @note Start request handling on the next tick so that the user
						* could add event listeners for "loadend" before the interceptor fires it.
						*/
						queueMicrotask(() => {
							(this.onRequest?.call(this, {
								request: fetchRequest,
								requestId: this.requestId
							}) || Promise.resolve()).finally(() => {
								if (!this[kIsRequestHandled]) {
									this.logger.verbose("request callback settled but request has not been handled (readystate %d), performing as-is...", this.request.readyState);
									return invoke();
								}
							});
						});
						break;
					}
					default: return invoke();
				}
			} });
			/**
			* Proxy the `.upload` property to gather the event listeners/callbacks.
			*/
			define(this.request, "upload", createProxy(this.request.upload, {
				setProperty: ([propertyName, nextValue], invoke) => {
					switch (propertyName) {
						case "onloadstart":
						case "onprogress":
						case "onaboart":
						case "onerror":
						case "onload":
						case "ontimeout":
						case "onloadend": {
							const eventName = propertyName.slice(2);
							this.registerUploadEvent(eventName, nextValue);
						}
					}
					return invoke();
				},
				methodCall: ([methodName, args], invoke) => {
					switch (methodName) {
						case "addEventListener": {
							const [eventName, listener] = args;
							this.registerUploadEvent(eventName, listener);
							this.logger.verbose("upload.addEventListener", eventName, listener);
							return invoke();
						}
					}
				}
			}));
		}
		registerEvent(eventName, listener) {
			const nextEvents = (this.events.get(eventName) || []).concat(listener);
			this.events.set(eventName, nextEvents);
			this.logger.verbose("registered event \"%s\"", eventName, listener);
		}
		registerUploadEvent(eventName, listener) {
			const nextEvents = (this.uploadEvents.get(eventName) || []).concat(listener);
			this.uploadEvents.set(eventName, nextEvents);
			this.logger.verbose("registered upload event \"%s\"", eventName, listener);
		}
		/**
		* Responds to the current request with the given
		* Fetch API `Response` instance.
		*/
		async respondWith(response) {
			/**
			* @note Since `XMLHttpRequestController` delegates the handling of the responses
			* to the "load" event listener that doesn't distinguish between the mocked and original
			* responses, mark the request that had a mocked response with a corresponding symbol.
			*
			* Mark this request as having a mocked response immediately since
			* calculating request/response total body length is asynchronous.
			*/
			this[kIsRequestHandled] = true;
			this.logger.verbose("responding with a mocked response: %d %s", response.status, response.statusText);
			FetchResponse.setUrl(this.url.href, response);
			Object.defineProperties(this.request, {
				response: {
					enumerable: true,
					configurable: false,
					get: () => this.response
				},
				responseText: {
					enumerable: true,
					configurable: false,
					get: () => this.responseText
				},
				responseXML: {
					enumerable: true,
					configurable: false,
					get: () => this.responseXML
				}
			});
			this.trigger("loadstart", this.request, {
				loaded: 0,
				total: 0
			});
			let requestBodyTransmitted = 0;
			let uploadComplete = false;
			if (this[kFetchRequest]) {
				const requestBodyLength = await getBodyByteLength(this[kFetchRequest].clone());
				if (!uploadComplete) this.trigger("loadstart", this.request.upload, {
					loaded: 0,
					total: requestBodyLength
				});
				const processRequestBodyChunkLength = (bytesLength) => {
					requestBodyTransmitted += bytesLength;
					if (requestBodyTransmitted < requestBodyLength) this.trigger("progress", this.request.upload, {
						loaded: requestBodyTransmitted,
						total: requestBodyLength
					});
				};
				const processRequestEndOfBody = () => {
					uploadComplete = true;
					this.trigger("progress", this.request.upload, {
						loaded: requestBodyTransmitted,
						total: requestBodyLength
					});
					this.trigger("load", this.request.upload, {
						loaded: requestBodyTransmitted,
						total: requestBodyLength
					});
					this.trigger("loadend", this.request.upload, {
						loaded: requestBodyTransmitted,
						total: requestBodyLength
					});
				};
				if (this[kFetchRequest]?.body != null) {
					const reader = this[kFetchRequest].body.getReader();
					while (true) {
						const { value, done } = await reader.read();
						if (done) {
							processRequestEndOfBody();
							break;
						}
						processRequestBodyChunkLength(value.byteLength);
					}
				} else processRequestEndOfBody();
			}
			let timedOut = false;
			const responseReadController = new AbortController();
			const requestErrorSteps = (event) => {
				this.setReadyState(this.request.DONE);
				if (!uploadComplete) {
					this.trigger(event, this.request.upload, {
						loaded: 0,
						total: 0
					});
					this.trigger("loadend", this.request.upload, {
						loaded: 0,
						total: 0
					});
				}
				this.trigger(event, this.request, {
					loaded: 0,
					total: 0
				});
				this.trigger("loadend", this.request, {
					loaded: 0,
					total: 0
				});
			};
			const processResponse = async (response) => {
				const handleErrors = () => {
					if (timedOut) requestErrorSteps("timeout");
					else if (responseReadController.signal.aborted) requestErrorSteps("abort");
					else if (isResponseError(response)) requestErrorSteps("error");
				};
				handleErrors();
				define(this.request, "status", response.status);
				define(this.request, "statusText", response.statusText);
				if (!this.request.responseURL) define(this.request, "responseURL", response.url);
				if (isResponseError(response)) return;
				/**
				* @note The response body length is derived ONLY from the "content-length" header.
				* If that response header is not set, the "total" in all progress events must be 0.
				*/
				const responseBodyLength = Number(response.headers.get("content-length") ?? "0");
				this.setReadyState(this.request.HEADERS_RECEIVED);
				let receivedBytes = 0;
				let lastReceivedResponseBytesAt = performance.now();
				const processResponseBodyChunk = (bytesLength) => {
					receivedBytes += bytesLength;
					const now = performance.now();
					const shouldBuffer = now - lastReceivedResponseBytesAt <= 60 && receivedBytes < responseBodyLength;
					lastReceivedResponseBytesAt = now;
					if (shouldBuffer) return;
					if (this.request.readyState === this.request.HEADERS_RECEIVED) this.setReadyState(this.request.LOADING, false);
					this.trigger("readystatechange", this.request);
					this.trigger("progress", this.request, {
						loaded: receivedBytes,
						total: responseBodyLength
					});
				};
				const processResponseBodyError = () => {
					requestErrorSteps("error");
				};
				const processResponseEndOfBody = async () => {
					handleErrors();
					if (isResponseError(response)) return;
					let transmitted = receivedBytes;
					this.setReadyState(this.request.DONE);
					this.trigger("load", this.request, {
						loaded: transmitted,
						total: responseBodyLength
					});
					this.trigger("loadend", this.request, {
						loaded: transmitted,
						total: responseBodyLength
					});
				};
				if (response.body == null) processResponseEndOfBody();
				else {
					const reader = response.body.getReader();
					while (true) {
						if (responseReadController.signal.aborted) break;
						try {
							const { value, done } = await reader.read();
							if (done) {
								processResponseEndOfBody();
								return;
							}
							processResponseBodyChunk(value.byteLength);
							this.responseBuffer = concatArrayBuffer(this.responseBuffer, value);
						} catch {
							processResponseBodyError();
						}
					}
				}
			};
			const [redirectError, finalResponse] = await until(() => {
				return this.followRedirects(response);
			});
			if (redirectError) return;
			processResponse(finalResponse);
			if (this.request.timeout) setTimeout(() => {
				if (this.request.readyState !== this.request.DONE) {
					timedOut = true;
					responseReadController.abort();
				}
			}, this.request.timeout);
			this.request.getResponseHeader = new Proxy(this.request.getResponseHeader, { apply: (_, __, args) => {
				this.logger.verbose("getResponseHeader", args[0]);
				if (this.request.readyState < this.request.HEADERS_RECEIVED) {
					this.logger.verbose("headers not received yet, returning null");
					return null;
				}
				const headerValue = finalResponse.headers.get(args[0]);
				this.logger.verbose("resolved response header \"%s\" to", args[0], headerValue);
				return headerValue;
			} });
			this.request.getAllResponseHeaders = new Proxy(this.request.getAllResponseHeaders, { apply: () => {
				this.logger.verbose("getAllResponseHeaders");
				if (this.request.readyState < this.request.HEADERS_RECEIVED) {
					this.logger.verbose("headers not received yet, returning empty string");
					return "";
				}
				const allHeaders = Array.from(finalResponse.headers).map(([headerName, headerValue]) => {
					return `${headerName}: ${headerValue}`;
				}).join("\r\n");
				this.logger.verbose("resolved all response headers to", allHeaders);
				return allHeaders;
			} });
		}
		responseBufferToText() {
			return decodeBuffer(this.responseBuffer);
		}
		get response() {
			this.logger.verbose("getResponse (responseType: %s)", this.request.responseType);
			if (this.request.readyState !== this.request.DONE) return null;
			switch (this.request.responseType) {
				case "json": {
					const responseJson = parseJson(this.responseBufferToText());
					this.logger.verbose("resolved response JSON", responseJson);
					return responseJson;
				}
				case "arraybuffer": {
					const arrayBuffer = toArrayBuffer(this.responseBuffer);
					this.logger.verbose("resolved response ArrayBuffer", arrayBuffer);
					return arrayBuffer;
				}
				case "blob": {
					const mimeType = this.request.getResponseHeader("Content-Type") || "text/plain";
					const responseBlob = new Blob([this.responseBufferToText()], { type: mimeType });
					this.logger.verbose("resolved response Blob (mime type: %s)", responseBlob, mimeType);
					return responseBlob;
				}
				default: {
					const responseText = this.responseBufferToText();
					this.logger.verbose("resolving \"%s\" response type as text", this.request.responseType, responseText);
					return responseText;
				}
			}
		}
		get responseText() {
			/**
			* Throw when trying to read the response body as text when the
			* "responseType" doesn't expect text. This just respects the spec better.
			* @see https://xhr.spec.whatwg.org/#the-responsetext-attribute
			*/
			invariant$1(this.request.responseType === "" || this.request.responseType === "text", "InvalidStateError: The object is in invalid state.");
			if (this.request.readyState !== this.request.LOADING && this.request.readyState !== this.request.DONE) return "";
			const responseText = this.responseBufferToText();
			this.logger.verbose("getResponseText: \"%s\"", responseText);
			return responseText;
		}
		get responseXML() {
			invariant$1(this.request.responseType === "" || this.request.responseType === "document", "InvalidStateError: The object is in invalid state.");
			if (this.request.readyState !== this.request.DONE) return null;
			const contentType = this.request.getResponseHeader("Content-Type") || "";
			if (typeof DOMParser === "undefined") {
				console.warn("Cannot retrieve XMLHttpRequest response body as XML: DOMParser is not defined. You are likely using an environment that is not browser or does not polyfill browser globals correctly.");
				return null;
			}
			if (isDomParserSupportedType(contentType)) return new DOMParser().parseFromString(this.responseBufferToText(), contentType);
			return null;
		}
		async followRedirects(response) {
			const redirectLocation = response.headers.get("location");
			if (!redirectLocation || !FetchResponse.isRedirectResponse(response.status)) return response;
			this.redirectCount++;
			if (this.redirectCount > MAX_REDIRECTS) throw new Error("Too many redirects");
			const redirectUrl = new URL(redirectLocation, location.href);
			const redirectMethod = FetchResponse.isResponseWithBody(response.status) ? this.method : "GET";
			const redirectResponse = await new Promise((resolve, reject) => {
				const request = new XMLHttpRequest();
				request.responseType = this.request.responseType;
				request.addEventListener("load", () => {
					this.url = new URL(request.responseURL);
					resolve(createResponse(request, request.response));
				});
				request.addEventListener("error", () => {
					this.errorWith();
					reject(/* @__PURE__ */ new Error("Redirect request failed"));
				});
				request.open(redirectMethod, redirectUrl.href);
				request.send();
			});
			return this.followRedirects(redirectResponse);
		}
		errorWith(error) {
			/**
			* @note Mark this request as handled even if it received a mock error.
			* This prevents the controller from trying to perform this request as-is.
			*/
			this[kIsRequestHandled] = true;
			this.logger.verbose("responding with an error");
			this.setReadyState(this.request.DONE);
			this.trigger("error", this.request);
			this.trigger("loadend", this.request);
		}
		/**
		* Transitions this request's `readyState` to the given one.
		*/
		setReadyState(nextReadyState, triggerReadyStateChangeEvent = true) {
			this.logger.verbose("setReadyState: %d -> %d", this.request.readyState, nextReadyState);
			if (this.request.readyState === nextReadyState) {
				this.logger.verbose("ready state identical, skipping transition...");
				return;
			}
			define(this.request, "readyState", nextReadyState);
			this.logger.verbose("set readyState to: %d", nextReadyState);
			if (!triggerReadyStateChangeEvent) return;
			if (nextReadyState !== this.request.UNSENT) {
				this.logger.verbose("triggering \"readystatechange\" event...");
				this.trigger("readystatechange", this.request);
			}
		}
		/**
		* Triggers given event on the `XMLHttpRequest` instance.
		*/
		trigger(eventName, target, options) {
			const callback = target[`on${eventName}`];
			const event = createEvent(target, eventName, options);
			this.logger.verbose("trigger \"%s\"", eventName, options || "");
			if (typeof callback === "function") {
				this.logger.verbose("found a direct \"%s\" callback, calling...", eventName);
				callback.call(target, event);
			}
			const events = target instanceof XMLHttpRequestUpload ? this.uploadEvents : this.events;
			for (const [registeredEventName, listeners] of events) if (registeredEventName === eventName) {
				this.logger.verbose("found %d listener(s) for \"%s\" event, calling...", listeners.length, eventName);
				listeners.forEach((listener) => listener.call(target, event));
			}
		}
		/**
		* Converts this `XMLHttpRequest` instance into a Fetch API `Request` instance.
		*/
		toFetchApiRequest(body) {
			this.logger.verbose("converting request to a Fetch API Request...");
			const resolvedBody = body instanceof Document ? body.documentElement.innerText : body;
			const fetchRequest = new FetchRequest(this.url.href, {
				method: this.method,
				headers: this.requestHeaders,
				/**
				* @see https://xhr.spec.whatwg.org/#cross-origin-credentials
				*/
				credentials: this.request.withCredentials ? "include" : "same-origin",
				body: resolvedBody
			});
			const headers = fetchRequest.headers;
			define(fetchRequest, "headers", createProxy(headers, { methodCall: ([methodName, args], invoke) => {
				const result = invoke();
				switch (methodName) {
					case "append":
					case "set": {
						const [headerName, headerValue] = args;
						/**
						* @note Forward only the headers the Fetch API Request accepted.
						* Forbidden request headers (e.g. "Cookie") are dropped silently
						* by the request's headers guard, and forwarding them makes
						* the browser refuse them with an error in the console.
						*/
						if (headers.has(headerName)) this.request.setRequestHeader(headerName, headerValue);
						break;
					}
					case "delete": {
						const [headerName] = args;
						console.warn(`XMLHttpRequest: Cannot remove a "${headerName}" header from the Fetch API representation of the "${fetchRequest.method} ${fetchRequest.url}" request. XMLHttpRequest headers cannot be removed.`);
						break;
					}
				}
				return result;
			} }));
			this.logger.verbose("converted request to a Fetch API Request!", fetchRequest);
			return fetchRequest;
		}
	};
	function toAbsoluteUrl(url) {
		/**
		* @note XMLHttpRequest interceptor may run in environments
		* that implement XMLHttpRequest but don't implement "location"
		* (for example, React Native). If that's the case, return the
		* input URL as-is (nothing to be relative to).
		* @see https://github.com/mswjs/msw/issues/1777
		*/
		if (typeof location === "undefined") return new URL(url);
		return new URL(url.toString(), location.href);
	}
	function define(target, property, value) {
		Reflect.defineProperty(target, property, {
			writable: true,
			enumerable: true,
			value
		});
	}
	/**
	* Create a proxied `XMLHttpRequest` class.
	* The proxied class establishes spies on certain methods,
	* allowing us to intercept requests and respond to them.
	*/
	function createXMLHttpRequestProxy({ emitter, logger }) {
		return new Proxy(globalThis.XMLHttpRequest, { construct(target, args, newTarget) {
			logger.verbose("constructed new XMLHttpRequest");
			const originalRequest = Reflect.construct(target, args, newTarget);
			/**
			* @note Forward prototype descriptors onto the proxied object.
			* XMLHttpRequest is implemented in JSDOM in a way that assigns
			* a bunch of descriptors, like "set responseType()" on the prototype.
			* With this propagation, we make sure that those descriptors trigger
			* when the user operates with the proxied request instance.
			*/
			const prototypeDescriptors = Object.getOwnPropertyDescriptors(target.prototype);
			for (const propertyName in prototypeDescriptors) Reflect.defineProperty(originalRequest, propertyName, prototypeDescriptors[propertyName]);
			const xhrRequestController = new XMLHttpRequestController(originalRequest, logger);
			xhrRequestController.onRequest = async function({ request, requestId }) {
				const controller = new RequestController(request, {
					passthrough: () => {
						this.logger.verbose("no mocked response received, performing request as-is...");
					},
					respondWith: async (response) => {
						await this.respondWith(response);
					},
					errorWith: (reason) => {
						this.logger.verbose("request errored %o", { error: reason });
						if (reason instanceof Error) this.errorWith(reason);
					}
				}, {
					logger,
					requestId
				});
				this.logger.verbose("awaiting mocked response");
				this.logger.verbose("emitting the \"request\" event for %s listener(s)...", emitter.listenerCount("request"));
				await handleRequest({
					initiator: this.request,
					request,
					requestId,
					controller,
					emitter,
					logger
				});
			};
			xhrRequestController.onResponse = async function({ response, responseType, request, requestId }) {
				this.logger.verbose("emitting the \"response\" event for %s listener(s)...", emitter.listenerCount("response"));
				await emitter.emitAsPromise(new HttpResponseEvent({
					initiator: this.request,
					response,
					responseType,
					request,
					requestId
				}));
			};
			return xhrRequestController.request;
		} });
	}
	const logger = createLogger("xhr");
	var XMLHttpRequestInterceptor = class extends Interceptor {
		static {
			this.symbol = Symbol.for("xhr-interceptor");
		}
		predicate() {
			return hasConfigurableGlobal("XMLHttpRequest");
		}
		setup() {
			logger.verbose("patching \"XMLHttpRequest\"...");
			this.subscriptions.push(patchesRegistry.applyPatch(globalThis, "XMLHttpRequest", () => {
				return createXMLHttpRequestProxy({
					emitter: this.emitter,
					logger
				});
			}));
			logger.verbose("global \"XMLHttpRequest\" patched!", globalThis.XMLHttpRequest.name);
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
		invariant$1(!isNodeProcess(), devUtils.formatMessage("Failed to execute `setupWorker` in a non-browser environment"));
		const network = defineNetwork({
			sources: [],
			handlers
		});
		return {
			get readyState() {
				return network.readyState;
			},
			async start(options) {
				invariant$1(network.readyState === 0, devUtils.formatMessage("Failed to call \"worker.start()\": the worker is already started. Remove the redundant \"worker.start()\" call."));
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
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/jsutils/instanceOf.mjs
	function prodInstanceOf(value, symbol) {
		return value?.__kind === symbol;
	}
	let instanceOf = prodInstanceOf;
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/jsutils/isObjectLike.mjs
	function isObjectLike(value) {
		return typeof value == "object" && value !== null;
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/jsutils/invariant.mjs
	function invariant(condition, message) {
		if (!condition) throw new Error(message ?? "Unexpected invariant triggered.");
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/location.mjs
	const LineRegExp = /\r\n|[\n\r]/g;
	function getLocation(source, position) {
		let lastLineStart = 0;
		let line = 1;
		for (const match of source.body.matchAll(LineRegExp)) {
			if (!(typeof match.index === "number")) invariant(false);
			if (match.index >= position) break;
			lastLineStart = match.index + match[0].length;
			line += 1;
		}
		return {
			line,
			column: position + 1 - lastLineStart
		};
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/printLocation.mjs
	function printLocation(location) {
		return printSourceLocation(location.source, getLocation(location.source, location.start));
	}
	function printSourceLocation(source, sourceLocation) {
		const firstLineColumnOffset = source.locationOffset.column - 1;
		const body = "".padStart(firstLineColumnOffset) + source.body;
		const lineIndex = sourceLocation.line - 1;
		const lineOffset = source.locationOffset.line - 1;
		const lineNum = sourceLocation.line + lineOffset;
		const columnOffset = sourceLocation.line === 1 ? firstLineColumnOffset : 0;
		const columnNum = sourceLocation.column + columnOffset;
		const locationStr = `${source.name}:${lineNum}:${columnNum}\n`;
		const lines = body.split(/\r\n|[\n\r]/g);
		const locationLine = lines[lineIndex];
		if (locationLine.length > 120) {
			const subLineIndex = Math.floor(columnNum / 80);
			const subLineColumnNum = columnNum % 80;
			const subLines = [];
			for (let i = 0; i < locationLine.length; i += 80) subLines.push(locationLine.slice(i, i + 80));
			return locationStr + printPrefixedLines([
				[`${lineNum} |`, subLines[0]],
				...subLines.slice(1, subLineIndex + 1).map((subLine) => ["|", subLine]),
				["|", "^".padStart(subLineColumnNum)],
				["|", subLines[subLineIndex + 1]]
			]);
		}
		return locationStr + printPrefixedLines([
			[`${lineNum - 1} |`, lines[lineIndex - 1]],
			[`${lineNum} |`, locationLine],
			["|", "^".padStart(columnNum)],
			[`${lineNum + 1} |`, lines[lineIndex + 1]]
		]);
	}
	function printPrefixedLines(lines) {
		const existingLines = lines.filter(([_, line]) => line !== void 0);
		const padLen = Math.max(...existingLines.map(([prefix]) => prefix.length));
		return existingLines.map(([prefix, line]) => prefix.padStart(padLen) + (line ? " " + line : "")).join("\n");
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/error/GraphQLError.mjs
	var GraphQLError = class GraphQLError extends Error {
		constructor(message, options = {}) {
			const { nodes, source, positions, path, originalError, cause, extensions } = options;
			const hasCause = "cause" in options;
			super(message, hasCause || originalError != null ? { cause: hasCause ? cause : originalError } : void 0);
			this.name = "GraphQLError";
			this.path = path ?? void 0;
			const underlyingError = originalError ?? (cause instanceof Error ? cause : void 0);
			this.originalError = underlyingError;
			this.nodes = undefinedIfEmpty(Array.isArray(nodes) ? nodes : nodes ? [nodes] : void 0);
			const nodeLocations = undefinedIfEmpty(this.nodes?.map((node) => node.loc).filter((loc) => loc != null));
			this.source = source ?? nodeLocations?.[0]?.source;
			this.positions = positions ?? nodeLocations?.map((loc) => loc.start);
			this.locations = positions && source ? positions.map((pos) => getLocation(source, pos)) : nodeLocations?.map((loc) => getLocation(loc.source, loc.start));
			const originalExtensions = isObjectLike(underlyingError?.extensions) ? underlyingError.extensions : void 0;
			this.extensions = extensions ?? originalExtensions ?? Object.create(null);
			Object.defineProperties(this, {
				message: {
					writable: true,
					enumerable: true
				},
				name: { enumerable: false },
				nodes: { enumerable: false },
				source: { enumerable: false },
				positions: { enumerable: false },
				originalError: { enumerable: false }
			});
			if (originalError?.stack != null) Object.defineProperty(this, "stack", {
				value: originalError.stack,
				writable: true,
				configurable: true
			});
			else if (Error.captureStackTrace != null) Error.captureStackTrace(this, GraphQLError);
			else Object.defineProperty(this, "stack", {
				value: Error().stack,
				writable: true,
				configurable: true
			});
		}
		get [Symbol.toStringTag]() {
			return "GraphQLError";
		}
		toString() {
			let output = this.message;
			if (this.nodes) {
				for (const node of this.nodes) if (node.loc) output += "\n\n" + printLocation(node.loc);
			} else if (this.source && this.locations) for (const location of this.locations) output += "\n\n" + printSourceLocation(this.source, location);
			return output;
		}
		toJSON() {
			const formattedError = { message: this.message };
			if (this.locations != null) formattedError.locations = this.locations;
			if (this.path != null) formattedError.path = this.path;
			if (this.extensions != null && Object.keys(this.extensions).length > 0) formattedError.extensions = this.extensions;
			return formattedError;
		}
	};
	function undefinedIfEmpty(array) {
		return array === void 0 || array.length === 0 ? void 0 : array;
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/ast.mjs
	var Location = class {
		constructor(startToken, endToken, source) {
			this.start = startToken.start;
			this.end = endToken.end;
			this.startToken = startToken;
			this.endToken = endToken;
			this.source = source;
		}
		get [Symbol.toStringTag]() {
			return "Location";
		}
		toJSON() {
			return {
				start: this.start,
				end: this.end
			};
		}
	};
	var Token = class {
		constructor(kind, start, end, line, column, value) {
			this.kind = kind;
			this.start = start;
			this.end = end;
			this.line = line;
			this.column = column;
			this.value = value;
			this.prev = null;
			this.next = null;
		}
		get [Symbol.toStringTag]() {
			return "Token";
		}
		toJSON() {
			return {
				kind: this.kind,
				value: this.value,
				line: this.line,
				column: this.column
			};
		}
	};
	new Set(Object.keys({
		Name: [],
		Document: ["definitions"],
		OperationDefinition: [
			"description",
			"name",
			"variableDefinitions",
			"directives",
			"selectionSet"
		],
		VariableDefinition: [
			"description",
			"variable",
			"type",
			"defaultValue",
			"directives"
		],
		Variable: ["name"],
		SelectionSet: ["selections"],
		Field: [
			"alias",
			"name",
			"arguments",
			"directives",
			"selectionSet"
		],
		Argument: ["name", "value"],
		FragmentArgument: ["name", "value"],
		FragmentSpread: [
			"name",
			"arguments",
			"directives"
		],
		InlineFragment: [
			"typeCondition",
			"directives",
			"selectionSet"
		],
		FragmentDefinition: [
			"description",
			"name",
			"variableDefinitions",
			"typeCondition",
			"directives",
			"selectionSet"
		],
		IntValue: [],
		FloatValue: [],
		StringValue: [],
		BooleanValue: [],
		NullValue: [],
		EnumValue: [],
		ListValue: ["values"],
		ObjectValue: ["fields"],
		ObjectField: ["name", "value"],
		Directive: ["name", "arguments"],
		NamedType: ["name"],
		ListType: ["type"],
		NonNullType: ["type"],
		SchemaDefinition: [
			"description",
			"directives",
			"operationTypes"
		],
		OperationTypeDefinition: ["type"],
		ScalarTypeDefinition: [
			"description",
			"name",
			"directives"
		],
		ObjectTypeDefinition: [
			"description",
			"name",
			"interfaces",
			"directives",
			"fields"
		],
		FieldDefinition: [
			"description",
			"name",
			"arguments",
			"type",
			"directives"
		],
		InputValueDefinition: [
			"description",
			"name",
			"type",
			"defaultValue",
			"directives"
		],
		InterfaceTypeDefinition: [
			"description",
			"name",
			"interfaces",
			"directives",
			"fields"
		],
		UnionTypeDefinition: [
			"description",
			"name",
			"directives",
			"types"
		],
		EnumTypeDefinition: [
			"description",
			"name",
			"directives",
			"values"
		],
		EnumValueDefinition: [
			"description",
			"name",
			"directives"
		],
		InputObjectTypeDefinition: [
			"description",
			"name",
			"directives",
			"fields"
		],
		DirectiveDefinition: [
			"description",
			"name",
			"arguments",
			"directives",
			"locations"
		],
		SchemaExtension: ["directives", "operationTypes"],
		DirectiveExtension: ["name", "directives"],
		ScalarTypeExtension: ["name", "directives"],
		ObjectTypeExtension: [
			"name",
			"interfaces",
			"directives",
			"fields"
		],
		InterfaceTypeExtension: [
			"name",
			"interfaces",
			"directives",
			"fields"
		],
		UnionTypeExtension: [
			"name",
			"directives",
			"types"
		],
		EnumTypeExtension: [
			"name",
			"directives",
			"values"
		],
		InputObjectTypeExtension: [
			"name",
			"directives",
			"fields"
		],
		TypeCoordinate: ["name"],
		MemberCoordinate: ["name", "memberName"],
		ArgumentCoordinate: [
			"name",
			"fieldName",
			"argumentName"
		],
		DirectiveCoordinate: ["name"],
		DirectiveArgumentCoordinate: ["name", "argumentName"]
	}));
	const OperationTypeNode = {
		QUERY: "query",
		MUTATION: "mutation",
		SUBSCRIPTION: "subscription"
	};
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/kinds_.mjs
	const NAME = "Name";
	const DOCUMENT = "Document";
	const OPERATION_DEFINITION = "OperationDefinition";
	const VARIABLE_DEFINITION = "VariableDefinition";
	const SELECTION_SET = "SelectionSet";
	const FIELD = "Field";
	const ARGUMENT = "Argument";
	const FRAGMENT_ARGUMENT = "FragmentArgument";
	const FRAGMENT_SPREAD = "FragmentSpread";
	const INLINE_FRAGMENT = "InlineFragment";
	const FRAGMENT_DEFINITION = "FragmentDefinition";
	const VARIABLE = "Variable";
	const INT = "IntValue";
	const FLOAT = "FloatValue";
	const STRING = "StringValue";
	const BOOLEAN = "BooleanValue";
	const NULL = "NullValue";
	const ENUM = "EnumValue";
	const LIST = "ListValue";
	const OBJECT = "ObjectValue";
	const OBJECT_FIELD = "ObjectField";
	const DIRECTIVE = "Directive";
	const NAMED_TYPE = "NamedType";
	const LIST_TYPE = "ListType";
	const NON_NULL_TYPE = "NonNullType";
	const SCHEMA_DEFINITION = "SchemaDefinition";
	const OPERATION_TYPE_DEFINITION = "OperationTypeDefinition";
	const SCALAR_TYPE_DEFINITION = "ScalarTypeDefinition";
	const OBJECT_TYPE_DEFINITION = "ObjectTypeDefinition";
	const FIELD_DEFINITION = "FieldDefinition";
	const INPUT_VALUE_DEFINITION = "InputValueDefinition";
	const INTERFACE_TYPE_DEFINITION = "InterfaceTypeDefinition";
	const UNION_TYPE_DEFINITION = "UnionTypeDefinition";
	const ENUM_TYPE_DEFINITION = "EnumTypeDefinition";
	const ENUM_VALUE_DEFINITION = "EnumValueDefinition";
	const INPUT_OBJECT_TYPE_DEFINITION = "InputObjectTypeDefinition";
	const DIRECTIVE_DEFINITION = "DirectiveDefinition";
	const SCHEMA_EXTENSION = "SchemaExtension";
	const DIRECTIVE_EXTENSION = "DirectiveExtension";
	const SCALAR_TYPE_EXTENSION = "ScalarTypeExtension";
	const OBJECT_TYPE_EXTENSION = "ObjectTypeExtension";
	const INTERFACE_TYPE_EXTENSION = "InterfaceTypeExtension";
	const UNION_TYPE_EXTENSION = "UnionTypeExtension";
	const ENUM_TYPE_EXTENSION = "EnumTypeExtension";
	const INPUT_OBJECT_TYPE_EXTENSION = "InputObjectTypeExtension";
	const TYPE_COORDINATE = "TypeCoordinate";
	const MEMBER_COORDINATE = "MemberCoordinate";
	const ARGUMENT_COORDINATE = "ArgumentCoordinate";
	const DIRECTIVE_COORDINATE = "DirectiveCoordinate";
	const DIRECTIVE_ARGUMENT_COORDINATE = "DirectiveArgumentCoordinate";
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/jsutils/devAssert.mjs
	function devAssert(condition, message) {
		if (!condition) throw new Error(message);
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/characterClasses.mjs
	function isWhiteSpace(code) {
		return code === 9 || code === 32;
	}
	function isDigit(code) {
		return code >= 48 && code <= 57;
	}
	function isLetter(code) {
		return code >= 97 && code <= 122 || code >= 65 && code <= 90;
	}
	function isNameStart(code) {
		return isLetter(code) || code === 95;
	}
	function isNameContinue(code) {
		return isLetter(code) || isDigit(code) || code === 95;
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/blockString.mjs
	function dedentBlockStringLines(lines) {
		let commonIndent = Number.MAX_SAFE_INTEGER;
		let firstNonEmptyLine = null;
		let lastNonEmptyLine = -1;
		for (let i = 0; i < lines.length; ++i) {
			const line = lines[i];
			const indent = leadingWhitespace(line);
			if (indent === line.length) continue;
			firstNonEmptyLine ??= i;
			lastNonEmptyLine = i;
			if (i !== 0 && indent < commonIndent) commonIndent = indent;
		}
		return lines.map((line, i) => i === 0 ? line : line.slice(commonIndent)).slice(firstNonEmptyLine ?? 0, lastNonEmptyLine + 1);
	}
	function leadingWhitespace(str) {
		let i = 0;
		while (i < str.length && isWhiteSpace(str.charCodeAt(i))) ++i;
		return i;
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/directiveLocation.mjs
	const DirectiveLocation = {
		QUERY: "QUERY",
		MUTATION: "MUTATION",
		SUBSCRIPTION: "SUBSCRIPTION",
		FIELD: "FIELD",
		FRAGMENT_DEFINITION: "FRAGMENT_DEFINITION",
		FRAGMENT_SPREAD: "FRAGMENT_SPREAD",
		INLINE_FRAGMENT: "INLINE_FRAGMENT",
		VARIABLE_DEFINITION: "VARIABLE_DEFINITION",
		FRAGMENT_VARIABLE_DEFINITION: "FRAGMENT_VARIABLE_DEFINITION",
		SCHEMA: "SCHEMA",
		SCALAR: "SCALAR",
		OBJECT: "OBJECT",
		FIELD_DEFINITION: "FIELD_DEFINITION",
		ARGUMENT_DEFINITION: "ARGUMENT_DEFINITION",
		INTERFACE: "INTERFACE",
		UNION: "UNION",
		ENUM: "ENUM",
		ENUM_VALUE: "ENUM_VALUE",
		INPUT_OBJECT: "INPUT_OBJECT",
		INPUT_FIELD_DEFINITION: "INPUT_FIELD_DEFINITION",
		DIRECTIVE_DEFINITION: "DIRECTIVE_DEFINITION"
	};
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/error/syntaxError.mjs
	function syntaxError(source, position, description) {
		return new GraphQLError(`Syntax Error: ${description}`, {
			source,
			positions: [position]
		});
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/diagnostics.mjs
	function resolveDiagnosticsChannel() {
		let dc;
		try {
			const processRef = globalThis.process;
			if (typeof processRef?.getBuiltinModule === "function") dc = processRef.getBuiltinModule("node:diagnostics_channel");
		} catch {}
		return dc;
	}
	const dc = resolveDiagnosticsChannel();
	const parseChannel = dc?.tracingChannel("graphql:parse");
	dc?.tracingChannel("graphql:validate");
	dc?.tracingChannel("graphql:execute");
	dc?.tracingChannel("graphql:execute:variableCoercion");
	dc?.tracingChannel("graphql:execute:rootSelectionSet");
	dc?.tracingChannel("graphql:subscribe");
	dc?.tracingChannel("graphql:resolve");
	const SUB_CHANNEL_KEYS = [
		"start",
		"end",
		"asyncStart",
		"asyncEnd",
		"error"
	];
	function shouldTrace(channel) {
		if (channel == null) return false;
		const aggregate = channel.hasSubscribers;
		if (aggregate !== void 0) return aggregate;
		for (const key of SUB_CHANNEL_KEYS) if (channel[key].hasSubscribers) return true;
		return false;
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/tokenKind.mjs
	const TokenKind = {
		SOF: "<SOF>",
		EOF: "<EOF>",
		BANG: "!",
		DOLLAR: "$",
		AMP: "&",
		PAREN_L: "(",
		PAREN_R: ")",
		DOT: ".",
		SPREAD: "...",
		COLON: ":",
		EQUALS: "=",
		AT: "@",
		BRACKET_L: "[",
		BRACKET_R: "]",
		BRACE_L: "{",
		PIPE: "|",
		BRACE_R: "}",
		NAME: "Name",
		INT: "Int",
		FLOAT: "Float",
		STRING: "String",
		BLOCK_STRING: "BlockString",
		COMMENT: "Comment"
	};
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/lexer.mjs
	var Lexer = class {
		constructor(source) {
			const startOfFileToken = new Token(TokenKind.SOF, 0, 0, 0, 0);
			this.source = source;
			this.lastToken = startOfFileToken;
			this.token = startOfFileToken;
			this.line = 1;
			this.lineStart = 0;
		}
		get [Symbol.toStringTag]() {
			return "Lexer";
		}
		advance() {
			this.lastToken = this.token;
			return this.token = this.lookahead();
		}
		lookahead() {
			let token = this.token;
			if (token.kind !== TokenKind.EOF) do
				if (token.next) token = token.next;
				else {
					const nextToken = readNextToken(this, token.end);
					token.next = nextToken;
					nextToken.prev = token;
					token = nextToken;
				}
			while (token.kind === TokenKind.COMMENT);
			return token;
		}
	};
	function isPunctuatorTokenKind(kind) {
		return kind === TokenKind.BANG || kind === TokenKind.DOLLAR || kind === TokenKind.AMP || kind === TokenKind.PAREN_L || kind === TokenKind.PAREN_R || kind === TokenKind.DOT || kind === TokenKind.SPREAD || kind === TokenKind.COLON || kind === TokenKind.EQUALS || kind === TokenKind.AT || kind === TokenKind.BRACKET_L || kind === TokenKind.BRACKET_R || kind === TokenKind.BRACE_L || kind === TokenKind.PIPE || kind === TokenKind.BRACE_R;
	}
	function isUnicodeScalarValue(code) {
		return code >= 0 && code <= 55295 || code >= 57344 && code <= 1114111;
	}
	function isSupplementaryCodePoint(body, location) {
		return isLeadingSurrogate(body.charCodeAt(location)) && isTrailingSurrogate(body.charCodeAt(location + 1));
	}
	function isLeadingSurrogate(code) {
		return code >= 55296 && code <= 56319;
	}
	function isTrailingSurrogate(code) {
		return code >= 56320 && code <= 57343;
	}
	function printCodePointAt(lexer, location) {
		const code = lexer.source.body.codePointAt(location);
		if (code === void 0) return TokenKind.EOF;
		else if (code >= 32 && code <= 126) {
			const char = String.fromCodePoint(code);
			return char === "\"" ? "'\"'" : `"${char}"`;
		}
		return "U+" + code.toString(16).toUpperCase().padStart(4, "0");
	}
	function createToken(lexer, kind, start, end, value) {
		const line = lexer.line;
		return new Token(kind, start, end, line, 1 + start - lexer.lineStart, value);
	}
	function readNextToken(lexer, start) {
		const body = lexer.source.body;
		const bodyLength = body.length;
		let position = start;
		while (position < bodyLength) {
			const code = body.charCodeAt(position);
			switch (code) {
				case 65279:
				case 9:
				case 32:
				case 44:
					++position;
					continue;
				case 10:
					++position;
					++lexer.line;
					lexer.lineStart = position;
					continue;
				case 13:
					if (body.charCodeAt(position + 1) === 10) position += 2;
					else ++position;
					++lexer.line;
					lexer.lineStart = position;
					continue;
				case 35: return readComment(lexer, position);
				case 33: return createToken(lexer, TokenKind.BANG, position, position + 1);
				case 36: return createToken(lexer, TokenKind.DOLLAR, position, position + 1);
				case 38: return createToken(lexer, TokenKind.AMP, position, position + 1);
				case 40: return createToken(lexer, TokenKind.PAREN_L, position, position + 1);
				case 41: return createToken(lexer, TokenKind.PAREN_R, position, position + 1);
				case 46: {
					const nextCode = body.charCodeAt(position + 1);
					if (nextCode === 46 && body.charCodeAt(position + 2) === 46) return createToken(lexer, TokenKind.SPREAD, position, position + 3);
					if (nextCode === 46) throw syntaxError(lexer.source, position, "Unexpected \"..\", did you mean \"...\"?");
					else if (isDigit(nextCode)) {
						const digits = lexer.source.body.slice(position + 1, readDigits(lexer, position + 1, nextCode));
						throw syntaxError(lexer.source, position, `Invalid number, expected digit before ".", did you mean "0.${digits}"?`);
					}
					break;
				}
				case 58: return createToken(lexer, TokenKind.COLON, position, position + 1);
				case 61: return createToken(lexer, TokenKind.EQUALS, position, position + 1);
				case 64: return createToken(lexer, TokenKind.AT, position, position + 1);
				case 91: return createToken(lexer, TokenKind.BRACKET_L, position, position + 1);
				case 93: return createToken(lexer, TokenKind.BRACKET_R, position, position + 1);
				case 123: return createToken(lexer, TokenKind.BRACE_L, position, position + 1);
				case 124: return createToken(lexer, TokenKind.PIPE, position, position + 1);
				case 125: return createToken(lexer, TokenKind.BRACE_R, position, position + 1);
				case 34:
					if (body.charCodeAt(position + 1) === 34 && body.charCodeAt(position + 2) === 34) return readBlockString(lexer, position);
					return readString(lexer, position);
			}
			if (isDigit(code) || code === 45) return readNumber(lexer, position, code);
			if (isNameStart(code)) return readName(lexer, position);
			throw syntaxError(lexer.source, position, code === 39 ? "Unexpected single quote character ('), did you mean to use a double quote (\")?" : isUnicodeScalarValue(code) || isSupplementaryCodePoint(body, position) ? `Unexpected character: ${printCodePointAt(lexer, position)}.` : `Invalid character: ${printCodePointAt(lexer, position)}.`);
		}
		return createToken(lexer, TokenKind.EOF, bodyLength, bodyLength);
	}
	function readComment(lexer, start) {
		const body = lexer.source.body;
		const bodyLength = body.length;
		let position = start + 1;
		while (position < bodyLength) {
			const code = body.charCodeAt(position);
			if (code === 10 || code === 13) break;
			if (isUnicodeScalarValue(code)) ++position;
			else if (isSupplementaryCodePoint(body, position)) position += 2;
			else break;
		}
		return createToken(lexer, TokenKind.COMMENT, start, position, body.slice(start + 1, position));
	}
	function readNumber(lexer, start, firstCode) {
		const body = lexer.source.body;
		let position = start;
		let code = firstCode;
		let isFloat = false;
		if (code === 45) code = body.charCodeAt(++position);
		if (code === 48) {
			code = body.charCodeAt(++position);
			if (isDigit(code)) throw syntaxError(lexer.source, position, `Invalid number, unexpected digit after 0: ${printCodePointAt(lexer, position)}.`);
		} else {
			position = readDigits(lexer, position, code);
			code = body.charCodeAt(position);
		}
		if (code === 46) {
			isFloat = true;
			code = body.charCodeAt(++position);
			position = readDigits(lexer, position, code);
			code = body.charCodeAt(position);
		}
		if (code === 69 || code === 101) {
			isFloat = true;
			code = body.charCodeAt(++position);
			if (code === 43 || code === 45) code = body.charCodeAt(++position);
			position = readDigits(lexer, position, code);
			code = body.charCodeAt(position);
		}
		if (code === 46 || isNameStart(code)) throw syntaxError(lexer.source, position, `Invalid number, expected digit but got: ${printCodePointAt(lexer, position)}.`);
		return createToken(lexer, isFloat ? TokenKind.FLOAT : TokenKind.INT, start, position, body.slice(start, position));
	}
	function readDigits(lexer, start, firstCode) {
		if (!isDigit(firstCode)) throw syntaxError(lexer.source, start, `Invalid number, expected digit but got: ${printCodePointAt(lexer, start)}.`);
		const body = lexer.source.body;
		let position = start + 1;
		while (isDigit(body.charCodeAt(position))) ++position;
		return position;
	}
	function readString(lexer, start) {
		const body = lexer.source.body;
		const bodyLength = body.length;
		let position = start + 1;
		let chunkStart = position;
		let value = "";
		while (position < bodyLength) {
			const code = body.charCodeAt(position);
			if (code === 34) {
				value += body.slice(chunkStart, position);
				return createToken(lexer, TokenKind.STRING, start, position + 1, value);
			}
			if (code === 92) {
				value += body.slice(chunkStart, position);
				const escape = body.charCodeAt(position + 1) === 117 ? body.charCodeAt(position + 2) === 123 ? readEscapedUnicodeVariableWidth(lexer, position) : readEscapedUnicodeFixedWidth(lexer, position) : readEscapedCharacter(lexer, position);
				value += escape.value;
				position += escape.size;
				chunkStart = position;
				continue;
			}
			if (code === 10 || code === 13) break;
			if (isUnicodeScalarValue(code)) ++position;
			else if (isSupplementaryCodePoint(body, position)) position += 2;
			else throw syntaxError(lexer.source, position, `Invalid character within String: ${printCodePointAt(lexer, position)}.`);
		}
		throw syntaxError(lexer.source, position, "Unterminated string.");
	}
	function readEscapedUnicodeVariableWidth(lexer, position) {
		const body = lexer.source.body;
		let point = 0;
		let size = 3;
		while (size < 12) {
			const code = body.charCodeAt(position + size++);
			if (code === 125) {
				if (size < 5 || !isUnicodeScalarValue(point)) break;
				return {
					value: String.fromCodePoint(point),
					size
				};
			}
			point = point << 4 | readHexDigit(code);
			if (point < 0) break;
		}
		throw syntaxError(lexer.source, position, `Invalid Unicode escape sequence: "${body.slice(position, position + size)}".`);
	}
	function readEscapedUnicodeFixedWidth(lexer, position) {
		const body = lexer.source.body;
		const code = read16BitHexCode(body, position + 2);
		if (isUnicodeScalarValue(code)) return {
			value: String.fromCodePoint(code),
			size: 6
		};
		if (isLeadingSurrogate(code)) {
			if (body.charCodeAt(position + 6) === 92 && body.charCodeAt(position + 7) === 117) {
				const trailingCode = read16BitHexCode(body, position + 8);
				if (isTrailingSurrogate(trailingCode)) return {
					value: String.fromCodePoint(code, trailingCode),
					size: 12
				};
			}
		}
		throw syntaxError(lexer.source, position, `Invalid Unicode escape sequence: "${body.slice(position, position + 6)}".`);
	}
	function read16BitHexCode(body, position) {
		return readHexDigit(body.charCodeAt(position)) << 12 | readHexDigit(body.charCodeAt(position + 1)) << 8 | readHexDigit(body.charCodeAt(position + 2)) << 4 | readHexDigit(body.charCodeAt(position + 3));
	}
	function readHexDigit(code) {
		return code >= 48 && code <= 57 ? code - 48 : code >= 65 && code <= 70 ? code - 55 : code >= 97 && code <= 102 ? code - 87 : -1;
	}
	function readEscapedCharacter(lexer, position) {
		const body = lexer.source.body;
		switch (body.charCodeAt(position + 1)) {
			case 34: return {
				value: "\"",
				size: 2
			};
			case 92: return {
				value: "\\",
				size: 2
			};
			case 47: return {
				value: "/",
				size: 2
			};
			case 98: return {
				value: "\b",
				size: 2
			};
			case 102: return {
				value: "\f",
				size: 2
			};
			case 110: return {
				value: "\n",
				size: 2
			};
			case 114: return {
				value: "\r",
				size: 2
			};
			case 116: return {
				value: "	",
				size: 2
			};
		}
		throw syntaxError(lexer.source, position, `Invalid character escape sequence: "${body.slice(position, position + 2)}".`);
	}
	function readBlockString(lexer, start) {
		const body = lexer.source.body;
		const bodyLength = body.length;
		let lineStart = lexer.lineStart;
		let position = start + 3;
		let chunkStart = position;
		let currentLine = "";
		const blockLines = [];
		while (position < bodyLength) {
			const code = body.charCodeAt(position);
			if (code === 34 && body.charCodeAt(position + 1) === 34 && body.charCodeAt(position + 2) === 34) {
				currentLine += body.slice(chunkStart, position);
				blockLines.push(currentLine);
				const token = createToken(lexer, TokenKind.BLOCK_STRING, start, position + 3, dedentBlockStringLines(blockLines).join("\n"));
				lexer.line += blockLines.length - 1;
				lexer.lineStart = lineStart;
				return token;
			}
			if (code === 92 && body.charCodeAt(position + 1) === 34 && body.charCodeAt(position + 2) === 34 && body.charCodeAt(position + 3) === 34) {
				currentLine += body.slice(chunkStart, position);
				chunkStart = position + 1;
				position += 4;
				continue;
			}
			if (code === 10 || code === 13) {
				currentLine += body.slice(chunkStart, position);
				blockLines.push(currentLine);
				if (code === 13 && body.charCodeAt(position + 1) === 10) position += 2;
				else ++position;
				currentLine = "";
				chunkStart = position;
				lineStart = position;
				continue;
			}
			if (isUnicodeScalarValue(code)) ++position;
			else if (isSupplementaryCodePoint(body, position)) position += 2;
			else throw syntaxError(lexer.source, position, `Invalid character within String: ${printCodePointAt(lexer, position)}.`);
		}
		throw syntaxError(lexer.source, position, "Unterminated string.");
	}
	function readName(lexer, start) {
		const body = lexer.source.body;
		const bodyLength = body.length;
		let position = start + 1;
		while (position < bodyLength) if (isNameContinue(body.charCodeAt(position))) ++position;
		else break;
		return createToken(lexer, TokenKind.NAME, start, position, body.slice(start, position));
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/source.mjs
	const sourceSymbol = Symbol("Source");
	var Source = class {
		constructor(body, name = "GraphQL request", locationOffset = {
			line: 1,
			column: 1
		}) {
			this.__kind = sourceSymbol;
			this.body = body;
			this.name = name;
			this.locationOffset = locationOffset;
			if (!(this.locationOffset.line > 0)) devAssert(false, "line in locationOffset is 1-indexed and must be positive.");
			if (!(this.locationOffset.column > 0)) devAssert(false, "column in locationOffset is 1-indexed and must be positive.");
		}
		get [Symbol.toStringTag]() {
			return "Source";
		}
	};
	function isSource(source) {
		return instanceOf(source, sourceSymbol, Source);
	}
	//#endregion
	//#region node_modules/.pnpm/graphql@17.0.2/node_modules/graphql/language/parser.mjs
	function parse(source, options) {
		return shouldTrace(parseChannel) ? parseChannel.traceSync(() => parseImpl(source, options), { source }) : parseImpl(source, options);
	}
	function parseImpl(source, options) {
		const parser = new Parser(source, options);
		const document = parser.parseDocument();
		Object.defineProperty(document, "tokenCount", {
			enumerable: false,
			value: parser.tokenCount
		});
		return document;
	}
	var Parser = class {
		constructor(source, options = {}) {
			const { lexer, ..._options } = options;
			if (lexer) this._lexer = lexer;
			else {
				const sourceObj = isSource(source) ? source : new Source(source);
				this._lexer = new Lexer(sourceObj);
			}
			this._options = _options;
			this._tokenCounter = 0;
		}
		get tokenCount() {
			return this._tokenCounter;
		}
		parseName() {
			const token = this.expectToken(TokenKind.NAME);
			return this.node(token, {
				kind: NAME,
				value: token.value
			});
		}
		parseDocument() {
			return this.node(this._lexer.token, {
				kind: DOCUMENT,
				definitions: this.many(TokenKind.SOF, this.parseDefinition, TokenKind.EOF)
			});
		}
		parseDefinition() {
			if (this.peek(TokenKind.BRACE_L)) return this.parseOperationDefinition();
			const hasDescription = this.peekDescription();
			const keywordToken = hasDescription ? this._lexer.lookahead() : this._lexer.token;
			if (hasDescription && keywordToken.kind === TokenKind.BRACE_L) throw syntaxError(this._lexer.source, this._lexer.token.start, "Unexpected description, descriptions are not supported on shorthand queries.");
			if (keywordToken.kind === TokenKind.NAME) {
				switch (keywordToken.value) {
					case "schema": return this.parseSchemaDefinition();
					case "scalar": return this.parseScalarTypeDefinition();
					case "type": return this.parseObjectTypeDefinition();
					case "interface": return this.parseInterfaceTypeDefinition();
					case "union": return this.parseUnionTypeDefinition();
					case "enum": return this.parseEnumTypeDefinition();
					case "input": return this.parseInputObjectTypeDefinition();
					case "directive": return this.parseDirectiveDefinition();
				}
				switch (keywordToken.value) {
					case "query":
					case "mutation":
					case "subscription": return this.parseOperationDefinition();
					case "fragment": return this.parseFragmentDefinition();
				}
				if (hasDescription) throw syntaxError(this._lexer.source, this._lexer.token.start, "Unexpected description, only GraphQL definitions support descriptions.");
				switch (keywordToken.value) {
					case "extend": return this.parseTypeSystemExtension();
				}
			}
			throw this.unexpected(keywordToken);
		}
		parseOperationDefinition() {
			const start = this._lexer.token;
			if (this.peek(TokenKind.BRACE_L)) return this.node(start, {
				kind: OPERATION_DEFINITION,
				operation: OperationTypeNode.QUERY,
				description: void 0,
				name: void 0,
				variableDefinitions: void 0,
				directives: void 0,
				selectionSet: this.parseSelectionSet()
			});
			const description = this.parseDescription();
			const operation = this.parseOperationType();
			let name;
			if (this.peek(TokenKind.NAME)) name = this.parseName();
			return this.node(start, {
				kind: OPERATION_DEFINITION,
				operation,
				description,
				name,
				variableDefinitions: this.parseVariableDefinitions(),
				directives: this.parseDirectives(false),
				selectionSet: this.parseSelectionSet()
			});
		}
		parseOperationType() {
			const operationToken = this.expectToken(TokenKind.NAME);
			switch (operationToken.value) {
				case "query": return OperationTypeNode.QUERY;
				case "mutation": return OperationTypeNode.MUTATION;
				case "subscription": return OperationTypeNode.SUBSCRIPTION;
			}
			throw this.unexpected(operationToken);
		}
		parseVariableDefinitions() {
			return this.optionalMany(TokenKind.PAREN_L, this.parseVariableDefinition, TokenKind.PAREN_R);
		}
		parseVariableDefinition() {
			return this.node(this._lexer.token, {
				kind: VARIABLE_DEFINITION,
				description: this.parseDescription(),
				variable: this.parseVariable(),
				type: (this.expectToken(TokenKind.COLON), this.parseTypeReference()),
				defaultValue: this.expectOptionalToken(TokenKind.EQUALS) ? this.parseConstValueLiteral() : void 0,
				directives: this.parseConstDirectives()
			});
		}
		parseVariable() {
			const start = this._lexer.token;
			this.expectToken(TokenKind.DOLLAR);
			return this.node(start, {
				kind: VARIABLE,
				name: this.parseName()
			});
		}
		parseSelectionSet() {
			return this.node(this._lexer.token, {
				kind: SELECTION_SET,
				selections: this.many(TokenKind.BRACE_L, this.parseSelection, TokenKind.BRACE_R)
			});
		}
		parseSelection() {
			return this.peek(TokenKind.SPREAD) ? this.parseFragment() : this.parseField();
		}
		parseField() {
			const start = this._lexer.token;
			const nameOrAlias = this.parseName();
			let alias;
			let name;
			if (this.expectOptionalToken(TokenKind.COLON)) {
				alias = nameOrAlias;
				name = this.parseName();
			} else name = nameOrAlias;
			return this.node(start, {
				kind: FIELD,
				alias,
				name,
				arguments: this.parseArguments(false),
				directives: this.parseDirectives(false),
				selectionSet: this.peek(TokenKind.BRACE_L) ? this.parseSelectionSet() : void 0
			});
		}
		parseArguments(isConst) {
			const item = isConst ? this.parseConstArgument : this.parseArgument;
			return this.optionalMany(TokenKind.PAREN_L, item, TokenKind.PAREN_R);
		}
		parseFragmentArguments() {
			const item = this.parseFragmentArgument;
			return this.optionalMany(TokenKind.PAREN_L, item, TokenKind.PAREN_R);
		}
		parseArgument(isConst = false) {
			const start = this._lexer.token;
			const name = this.parseName();
			this.expectToken(TokenKind.COLON);
			return this.node(start, {
				kind: ARGUMENT,
				name,
				value: this.parseValueLiteral(isConst)
			});
		}
		parseConstArgument() {
			return this.parseArgument(true);
		}
		parseFragmentArgument() {
			const start = this._lexer.token;
			const name = this.parseName();
			this.expectToken(TokenKind.COLON);
			return this.node(start, {
				kind: FRAGMENT_ARGUMENT,
				name,
				value: this.parseValueLiteral(false)
			});
		}
		parseFragment() {
			const start = this._lexer.token;
			this.expectToken(TokenKind.SPREAD);
			const hasTypeCondition = this.expectOptionalKeyword("on");
			if (!hasTypeCondition && this.peek(TokenKind.NAME)) {
				const name = this.parseFragmentName();
				if (this.peek(TokenKind.PAREN_L) && this._options.experimentalFragmentArguments) return this.node(start, {
					kind: FRAGMENT_SPREAD,
					name,
					arguments: this.parseFragmentArguments(),
					directives: this.parseDirectives(false)
				});
				return this.node(start, {
					kind: FRAGMENT_SPREAD,
					name,
					directives: this.parseDirectives(false)
				});
			}
			return this.node(start, {
				kind: INLINE_FRAGMENT,
				typeCondition: hasTypeCondition ? this.parseNamedType() : void 0,
				directives: this.parseDirectives(false),
				selectionSet: this.parseSelectionSet()
			});
		}
		parseFragmentDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("fragment");
			if (this._options.experimentalFragmentArguments === true) return this.node(start, {
				kind: FRAGMENT_DEFINITION,
				description,
				name: this.parseFragmentName(),
				variableDefinitions: this.parseVariableDefinitions(),
				typeCondition: (this.expectKeyword("on"), this.parseNamedType()),
				directives: this.parseDirectives(false),
				selectionSet: this.parseSelectionSet()
			});
			return this.node(start, {
				kind: FRAGMENT_DEFINITION,
				description,
				name: this.parseFragmentName(),
				typeCondition: (this.expectKeyword("on"), this.parseNamedType()),
				directives: this.parseDirectives(false),
				selectionSet: this.parseSelectionSet()
			});
		}
		parseFragmentName() {
			if (this._lexer.token.value === "on") throw this.unexpected();
			return this.parseName();
		}
		parseValueLiteral(isConst) {
			const token = this._lexer.token;
			switch (token.kind) {
				case TokenKind.BRACKET_L: return this.parseList(isConst);
				case TokenKind.BRACE_L: return this.parseObject(isConst);
				case TokenKind.INT:
					this.advanceLexer();
					return this.node(token, {
						kind: INT,
						value: token.value
					});
				case TokenKind.FLOAT:
					this.advanceLexer();
					return this.node(token, {
						kind: FLOAT,
						value: token.value
					});
				case TokenKind.STRING:
				case TokenKind.BLOCK_STRING: return this.parseStringLiteral();
				case TokenKind.NAME:
					this.advanceLexer();
					switch (token.value) {
						case "true": return this.node(token, {
							kind: BOOLEAN,
							value: true
						});
						case "false": return this.node(token, {
							kind: BOOLEAN,
							value: false
						});
						case "null": return this.node(token, { kind: NULL });
						default: return this.node(token, {
							kind: ENUM,
							value: token.value
						});
					}
				case TokenKind.DOLLAR:
					if (isConst) {
						this.expectToken(TokenKind.DOLLAR);
						if (this._lexer.token.kind === TokenKind.NAME) {
							const varName = this._lexer.token.value;
							throw syntaxError(this._lexer.source, token.start, `Unexpected variable "$${varName}" in constant value.`);
						} else throw this.unexpected(token);
					}
					return this.parseVariable();
				default: throw this.unexpected();
			}
		}
		parseConstValueLiteral() {
			return this.parseValueLiteral(true);
		}
		parseStringLiteral() {
			const token = this._lexer.token;
			this.advanceLexer();
			return this.node(token, {
				kind: STRING,
				value: token.value,
				block: token.kind === TokenKind.BLOCK_STRING
			});
		}
		parseList(isConst) {
			const item = () => this.parseValueLiteral(isConst);
			return this.node(this._lexer.token, {
				kind: LIST,
				values: this.any(TokenKind.BRACKET_L, item, TokenKind.BRACKET_R)
			});
		}
		parseObject(isConst) {
			const item = () => this.parseObjectField(isConst);
			return this.node(this._lexer.token, {
				kind: OBJECT,
				fields: this.any(TokenKind.BRACE_L, item, TokenKind.BRACE_R)
			});
		}
		parseObjectField(isConst) {
			const start = this._lexer.token;
			const name = this.parseName();
			this.expectToken(TokenKind.COLON);
			return this.node(start, {
				kind: OBJECT_FIELD,
				name,
				value: this.parseValueLiteral(isConst)
			});
		}
		parseDirectives(isConst) {
			const directives = [];
			while (this.peek(TokenKind.AT)) directives.push(this.parseDirective(isConst));
			if (directives.length) return directives;
		}
		parseConstDirectives() {
			return this.parseDirectives(true);
		}
		parseDirective(isConst) {
			const start = this._lexer.token;
			this.expectToken(TokenKind.AT);
			return this.node(start, {
				kind: DIRECTIVE,
				name: this.parseName(),
				arguments: this.parseArguments(isConst)
			});
		}
		parseTypeReference() {
			const start = this._lexer.token;
			let type;
			if (this.expectOptionalToken(TokenKind.BRACKET_L)) {
				const innerType = this.parseTypeReference();
				this.expectToken(TokenKind.BRACKET_R);
				type = this.node(start, {
					kind: LIST_TYPE,
					type: innerType
				});
			} else type = this.parseNamedType();
			if (this.expectOptionalToken(TokenKind.BANG)) return this.node(start, {
				kind: NON_NULL_TYPE,
				type
			});
			return type;
		}
		parseNamedType() {
			return this.node(this._lexer.token, {
				kind: NAMED_TYPE,
				name: this.parseName()
			});
		}
		peekDescription() {
			return this.peek(TokenKind.STRING) || this.peek(TokenKind.BLOCK_STRING);
		}
		parseDescription() {
			if (this.peekDescription()) return this.parseStringLiteral();
		}
		parseSchemaDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("schema");
			const directives = this.parseConstDirectives();
			const operationTypes = this.many(TokenKind.BRACE_L, this.parseOperationTypeDefinition, TokenKind.BRACE_R);
			return this.node(start, {
				kind: SCHEMA_DEFINITION,
				description,
				directives,
				operationTypes
			});
		}
		parseOperationTypeDefinition() {
			const start = this._lexer.token;
			const operation = this.parseOperationType();
			this.expectToken(TokenKind.COLON);
			const type = this.parseNamedType();
			return this.node(start, {
				kind: OPERATION_TYPE_DEFINITION,
				operation,
				type
			});
		}
		parseScalarTypeDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("scalar");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			return this.node(start, {
				kind: SCALAR_TYPE_DEFINITION,
				description,
				name,
				directives
			});
		}
		parseObjectTypeDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("type");
			const name = this.parseName();
			const interfaces = this.parseImplementsInterfaces();
			const directives = this.parseConstDirectives();
			const fields = this.parseFieldsDefinition();
			return this.node(start, {
				kind: OBJECT_TYPE_DEFINITION,
				description,
				name,
				interfaces,
				directives,
				fields
			});
		}
		parseImplementsInterfaces() {
			return this.expectOptionalKeyword("implements") ? this.delimitedMany(TokenKind.AMP, this.parseNamedType) : void 0;
		}
		parseFieldsDefinition() {
			return this.optionalMany(TokenKind.BRACE_L, this.parseFieldDefinition, TokenKind.BRACE_R);
		}
		parseFieldDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			const name = this.parseName();
			const args = this.parseArgumentDefs();
			this.expectToken(TokenKind.COLON);
			const type = this.parseTypeReference();
			const directives = this.parseConstDirectives();
			return this.node(start, {
				kind: FIELD_DEFINITION,
				description,
				name,
				arguments: args,
				type,
				directives
			});
		}
		parseArgumentDefs() {
			return this.optionalMany(TokenKind.PAREN_L, this.parseInputValueDef, TokenKind.PAREN_R);
		}
		parseInputValueDef() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			const name = this.parseName();
			this.expectToken(TokenKind.COLON);
			const type = this.parseTypeReference();
			let defaultValue;
			if (this.expectOptionalToken(TokenKind.EQUALS)) defaultValue = this.parseConstValueLiteral();
			const directives = this.parseConstDirectives();
			return this.node(start, {
				kind: INPUT_VALUE_DEFINITION,
				description,
				name,
				type,
				defaultValue,
				directives
			});
		}
		parseInterfaceTypeDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("interface");
			const name = this.parseName();
			const interfaces = this.parseImplementsInterfaces();
			const directives = this.parseConstDirectives();
			const fields = this.parseFieldsDefinition();
			return this.node(start, {
				kind: INTERFACE_TYPE_DEFINITION,
				description,
				name,
				interfaces,
				directives,
				fields
			});
		}
		parseUnionTypeDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("union");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			const types = this.parseUnionMemberTypes();
			return this.node(start, {
				kind: UNION_TYPE_DEFINITION,
				description,
				name,
				directives,
				types
			});
		}
		parseUnionMemberTypes() {
			return this.expectOptionalToken(TokenKind.EQUALS) ? this.delimitedMany(TokenKind.PIPE, this.parseNamedType) : void 0;
		}
		parseEnumTypeDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("enum");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			const values = this.parseEnumValuesDefinition();
			return this.node(start, {
				kind: ENUM_TYPE_DEFINITION,
				description,
				name,
				directives,
				values
			});
		}
		parseEnumValuesDefinition() {
			return this.optionalMany(TokenKind.BRACE_L, this.parseEnumValueDefinition, TokenKind.BRACE_R);
		}
		parseEnumValueDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			const name = this.parseEnumValueName();
			const directives = this.parseConstDirectives();
			return this.node(start, {
				kind: ENUM_VALUE_DEFINITION,
				description,
				name,
				directives
			});
		}
		parseEnumValueName() {
			if (this._lexer.token.value === "true" || this._lexer.token.value === "false" || this._lexer.token.value === "null") throw syntaxError(this._lexer.source, this._lexer.token.start, `${getTokenDesc(this._lexer.token)} is reserved and cannot be used for an enum value.`);
			return this.parseName();
		}
		parseInputObjectTypeDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("input");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			const fields = this.parseInputFieldsDefinition();
			return this.node(start, {
				kind: INPUT_OBJECT_TYPE_DEFINITION,
				description,
				name,
				directives,
				fields
			});
		}
		parseInputFieldsDefinition() {
			return this.optionalMany(TokenKind.BRACE_L, this.parseInputValueDef, TokenKind.BRACE_R);
		}
		parseTypeSystemExtension() {
			const keywordToken = this._lexer.lookahead();
			if (keywordToken.kind === TokenKind.NAME) switch (keywordToken.value) {
				case "schema": return this.parseSchemaExtension();
				case "scalar": return this.parseScalarTypeExtension();
				case "type": return this.parseObjectTypeExtension();
				case "interface": return this.parseInterfaceTypeExtension();
				case "union": return this.parseUnionTypeExtension();
				case "enum": return this.parseEnumTypeExtension();
				case "input": return this.parseInputObjectTypeExtension();
				case "directive": return this.parseDirectiveExtension();
			}
			throw this.unexpected(keywordToken);
		}
		parseSchemaExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("schema");
			const directives = this.parseConstDirectives();
			const operationTypes = this.optionalMany(TokenKind.BRACE_L, this.parseOperationTypeDefinition, TokenKind.BRACE_R);
			if (directives === void 0 && operationTypes === void 0) throw this.unexpected();
			return this.node(start, {
				kind: SCHEMA_EXTENSION,
				directives,
				operationTypes
			});
		}
		parseScalarTypeExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("scalar");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			if (directives === void 0) throw this.unexpected();
			return this.node(start, {
				kind: SCALAR_TYPE_EXTENSION,
				name,
				directives
			});
		}
		parseObjectTypeExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("type");
			const name = this.parseName();
			const interfaces = this.parseImplementsInterfaces();
			const directives = this.parseConstDirectives();
			const fields = this.parseFieldsDefinition();
			if (interfaces === void 0 && directives === void 0 && fields === void 0) throw this.unexpected();
			return this.node(start, {
				kind: OBJECT_TYPE_EXTENSION,
				name,
				interfaces,
				directives,
				fields
			});
		}
		parseInterfaceTypeExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("interface");
			const name = this.parseName();
			const interfaces = this.parseImplementsInterfaces();
			const directives = this.parseConstDirectives();
			const fields = this.parseFieldsDefinition();
			if (interfaces === void 0 && directives === void 0 && fields === void 0) throw this.unexpected();
			return this.node(start, {
				kind: INTERFACE_TYPE_EXTENSION,
				name,
				interfaces,
				directives,
				fields
			});
		}
		parseUnionTypeExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("union");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			const types = this.parseUnionMemberTypes();
			if (directives === void 0 && types === void 0) throw this.unexpected();
			return this.node(start, {
				kind: UNION_TYPE_EXTENSION,
				name,
				directives,
				types
			});
		}
		parseEnumTypeExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("enum");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			const values = this.parseEnumValuesDefinition();
			if (directives === void 0 && values === void 0) throw this.unexpected();
			return this.node(start, {
				kind: ENUM_TYPE_EXTENSION,
				name,
				directives,
				values
			});
		}
		parseInputObjectTypeExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("input");
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			const fields = this.parseInputFieldsDefinition();
			if (directives === void 0 && fields === void 0) throw this.unexpected();
			return this.node(start, {
				kind: INPUT_OBJECT_TYPE_EXTENSION,
				name,
				directives,
				fields
			});
		}
		parseDirectiveExtension() {
			const start = this._lexer.token;
			this.expectKeyword("extend");
			this.expectKeyword("directive");
			this.expectToken(TokenKind.AT);
			const name = this.parseName();
			const directives = this.parseConstDirectives();
			if (directives === void 0) throw this.unexpected();
			return this.node(start, {
				kind: DIRECTIVE_EXTENSION,
				name,
				directives
			});
		}
		parseDirectiveDefinition() {
			const start = this._lexer.token;
			const description = this.parseDescription();
			this.expectKeyword("directive");
			this.expectToken(TokenKind.AT);
			const name = this.parseName();
			const args = this.parseArgumentDefs();
			const directives = this.parseConstDirectives();
			const repeatable = this.expectOptionalKeyword("repeatable");
			this.expectKeyword("on");
			const locations = this.parseDirectiveLocations();
			return this.node(start, {
				kind: DIRECTIVE_DEFINITION,
				description,
				name,
				arguments: args,
				directives,
				repeatable,
				locations
			});
		}
		parseDirectiveLocations() {
			return this.delimitedMany(TokenKind.PIPE, this.parseDirectiveLocation);
		}
		parseDirectiveLocation() {
			const start = this._lexer.token;
			const name = this.parseName();
			if (Object.hasOwn(DirectiveLocation, name.value)) return name;
			throw this.unexpected(start);
		}
		parseSchemaCoordinate() {
			const start = this._lexer.token;
			const ofDirective = this.expectOptionalToken(TokenKind.AT);
			const name = this.parseName();
			let memberName;
			if (!ofDirective && this.expectOptionalToken(TokenKind.DOT)) memberName = this.parseName();
			let argumentName;
			if ((ofDirective || memberName) && this.expectOptionalToken(TokenKind.PAREN_L)) {
				argumentName = this.parseName();
				this.expectToken(TokenKind.COLON);
				this.expectToken(TokenKind.PAREN_R);
			}
			if (ofDirective) {
				if (argumentName) return this.node(start, {
					kind: DIRECTIVE_ARGUMENT_COORDINATE,
					name,
					argumentName
				});
				return this.node(start, {
					kind: DIRECTIVE_COORDINATE,
					name
				});
			} else if (memberName) {
				if (argumentName) return this.node(start, {
					kind: ARGUMENT_COORDINATE,
					name,
					fieldName: memberName,
					argumentName
				});
				return this.node(start, {
					kind: MEMBER_COORDINATE,
					name,
					memberName
				});
			}
			return this.node(start, {
				kind: TYPE_COORDINATE,
				name
			});
		}
		node(startToken, node) {
			if (this._options.noLocation !== true) node.loc = new Location(startToken, this._lexer.lastToken, this._lexer.source);
			return node;
		}
		peek(kind) {
			return this._lexer.token.kind === kind;
		}
		expectToken(kind) {
			const token = this._lexer.token;
			if (token.kind === kind) {
				this.advanceLexer();
				return token;
			}
			throw syntaxError(this._lexer.source, token.start, `Expected ${getTokenKindDesc(kind)}, found ${getTokenDesc(token)}.`);
		}
		expectOptionalToken(kind) {
			if (this._lexer.token.kind === kind) {
				this.advanceLexer();
				return true;
			}
			return false;
		}
		expectKeyword(value) {
			const token = this._lexer.token;
			if (token.kind === TokenKind.NAME && token.value === value) this.advanceLexer();
			else throw syntaxError(this._lexer.source, token.start, `Expected "${value}", found ${getTokenDesc(token)}.`);
		}
		expectOptionalKeyword(value) {
			const token = this._lexer.token;
			if (token.kind === TokenKind.NAME && token.value === value) {
				this.advanceLexer();
				return true;
			}
			return false;
		}
		unexpected(atToken) {
			const token = atToken ?? this._lexer.token;
			return syntaxError(this._lexer.source, token.start, `Unexpected ${getTokenDesc(token)}.`);
		}
		any(openKind, parseFn, closeKind) {
			this.expectToken(openKind);
			const nodes = [];
			while (!this.expectOptionalToken(closeKind)) nodes.push(parseFn.call(this));
			return nodes;
		}
		optionalMany(openKind, parseFn, closeKind) {
			if (this.expectOptionalToken(openKind)) {
				const nodes = [];
				do
					nodes.push(parseFn.call(this));
				while (!this.expectOptionalToken(closeKind));
				return nodes;
			}
		}
		many(openKind, parseFn, closeKind) {
			this.expectToken(openKind);
			const nodes = [];
			do
				nodes.push(parseFn.call(this));
			while (!this.expectOptionalToken(closeKind));
			return nodes;
		}
		delimitedMany(delimiterKind, parseFn) {
			this.expectOptionalToken(delimiterKind);
			const nodes = [];
			do
				nodes.push(parseFn.call(this));
			while (this.expectOptionalToken(delimiterKind));
			return nodes;
		}
		advanceLexer() {
			const { maxTokens } = this._options;
			const token = this._lexer.advance();
			if (token.kind !== TokenKind.EOF) {
				++this._tokenCounter;
				if (maxTokens !== void 0 && this._tokenCounter > maxTokens) throw syntaxError(this._lexer.source, token.start, `Document contains more than ${maxTokens} tokens. Parsing aborted.`);
			}
		}
	};
	function getTokenDesc(token) {
		const value = token.value;
		return getTokenKindDesc(token.kind) + (value != null ? ` "${value}"` : "");
	}
	function getTokenKindDesc(kind) {
		return isPunctuatorTokenKind(kind) ? `"${kind}"` : kind;
	}
	//#endregion
	//#region node_modules/.pnpm/set-cookie-parser@3.1.2/node_modules/set-cookie-parser/lib/set-cookie.js
	var defaultParseOptions = {
		decodeValues: true,
		map: false,
		silent: false,
		split: "auto"
	};
	function isForbiddenKey(key) {
		return typeof key !== "string" || key in {};
	}
	function createNullObj() {
		return Object.create(null);
	}
	function isNonEmptyString(str) {
		return typeof str === "string" && !!str.trim();
	}
	function parseString(setCookieValue, options) {
		var parts = setCookieValue.split(";").filter(isNonEmptyString);
		var nameValuePairStr = parts.shift();
		if (!nameValuePairStr) return null;
		var parsed = parseNameValuePair(nameValuePairStr);
		var name = parsed.name;
		var value = parsed.value;
		options = options ? Object.assign({}, defaultParseOptions, options) : defaultParseOptions;
		if (isForbiddenKey(name)) return null;
		try {
			value = options.decodeValues ? decodeURIComponent(value) : value;
		} catch (e) {
			console.error("set-cookie-parser: failed to decode cookie value. Set options.decodeValues=false to disable decoding.", e);
		}
		var cookie = createNullObj();
		cookie.name = name;
		cookie.value = value;
		parts.forEach(function(part) {
			var sides = part.split("=");
			var key = sides.shift().trim().toLowerCase();
			if (isForbiddenKey(key)) return;
			var value = sides.join("=").trim();
			if (key === "expires") cookie.expires = new Date(value);
			else if (key === "max-age") {
				var n = parseInt(value, 10);
				if (!Number.isNaN(n)) cookie.maxAge = n;
			} else if (key === "secure") cookie.secure = true;
			else if (key === "httponly") cookie.httpOnly = true;
			else if (key === "samesite") cookie.sameSite = value;
			else if (key === "partitioned") cookie.partitioned = true;
			else if (key) cookie[key] = value;
		});
		return cookie;
	}
	function parseNameValuePair(nameValuePairStr) {
		var name = "";
		var value = "";
		var nameValueArr = nameValuePairStr.split("=");
		if (nameValueArr.length > 1) {
			name = nameValueArr.shift();
			value = nameValueArr.join("=");
		} else value = nameValuePairStr;
		return {
			name,
			value
		};
	}
	function parseSetCookie(input, options) {
		options = options ? Object.assign({}, defaultParseOptions, options) : defaultParseOptions;
		if (!input) {
			if (!options.map) return [];
			else return createNullObj();
		}
		if (input.headers) {
			if (typeof input.headers.getSetCookie === "function") input = input.headers.getSetCookie();
			else if (input.headers["set-cookie"]) input = input.headers["set-cookie"];
			else {
				var sch = input.headers[Object.keys(input.headers).find(function(key) {
					return key.toLowerCase() === "set-cookie";
				})];
				if (!sch && input.headers.cookie && !options.silent) console.warn("Warning: set-cookie-parser appears to have been called on a request object. It is designed to parse Set-Cookie headers from responses, not Cookie headers from requests. Set the option {silent: true} to suppress this warning.");
				input = sch;
			}
		}
		var split = options.split;
		var isArray = Array.isArray(input);
		if (split === "auto") split = !isArray;
		if (!isArray) input = [input];
		input = input.filter(isNonEmptyString);
		if (split) input = input.map(splitCookiesString).flat();
		if (!options.map) return input.map(function(str) {
			return parseString(str, options);
		}).filter(Boolean);
		else {
			var cookies = createNullObj();
			return input.reduce(function(cookies, str) {
				var cookie = parseString(str, options);
				if (cookie && !isForbiddenKey(cookie.name)) cookies[cookie.name] = cookie;
				return cookies;
			}, cookies);
		}
	}
	function splitCookiesString(cookiesString) {
		if (Array.isArray(cookiesString)) return cookiesString;
		if (typeof cookiesString !== "string") return [];
		var cookiesStrings = [];
		var pos = 0;
		var start;
		var ch;
		var lastComma;
		var nextStart;
		var cookiesSeparatorFound;
		function skipWhitespace() {
			while (pos < cookiesString.length && /\s/.test(cookiesString.charAt(pos))) pos += 1;
			return pos < cookiesString.length;
		}
		function notSpecialChar() {
			ch = cookiesString.charAt(pos);
			return ch !== "=" && ch !== ";" && ch !== ",";
		}
		while (pos < cookiesString.length) {
			start = pos;
			cookiesSeparatorFound = false;
			while (skipWhitespace()) {
				ch = cookiesString.charAt(pos);
				if (ch === ",") {
					lastComma = pos;
					pos += 1;
					skipWhitespace();
					nextStart = pos;
					while (pos < cookiesString.length && notSpecialChar()) pos += 1;
					if (pos < cookiesString.length && cookiesString.charAt(pos) === "=") {
						cookiesSeparatorFound = true;
						pos = nextStart;
						cookiesStrings.push(cookiesString.substring(start, lastComma));
						start = pos;
					} else pos = lastComma + 1;
				} else pos += 1;
			}
			if (!cookiesSeparatorFound || pos >= cookiesString.length) cookiesStrings.push(cookiesString.substring(start, cookiesString.length));
		}
		return cookiesStrings;
	}
	parseSetCookie.parseSetCookie = parseSetCookie;
	parseSetCookie.parse = parseSetCookie;
	parseSetCookie.parseString = parseString;
	parseSetCookie.splitCookiesString = splitCookiesString;
	//#endregion
	//#region node_modules/.pnpm/headers-polyfill@5.0.1/node_modules/headers-polyfill/lib/index.mjs
	const HEADERS_INVALID_CHARACTERS = /[^a-z0-9\-#$%&'*+.^_`|~]/i;
	function normalizeHeaderName(name) {
		if (HEADERS_INVALID_CHARACTERS.test(name) || name.trim() === "") throw new TypeError("Invalid character in header field name");
		return name.trim().toLowerCase();
	}
	const charCodesToRemove = [
		String.fromCharCode(10),
		String.fromCharCode(13),
		String.fromCharCode(9),
		String.fromCharCode(32)
	];
	const HEADER_VALUE_REMOVE_REGEXP = new RegExp(`(^[${charCodesToRemove.join("")}]|$[${charCodesToRemove.join("")}])`, "g");
	/**
	* Normalize the given header value.
	* @see https://fetch.spec.whatwg.org/#concept-header-value-normalize
	*/
	function normalizeHeaderValue(value) {
		return value.replace(HEADER_VALUE_REMOVE_REGEXP, "");
	}
	/**
	* Validate the given header name.
	* @see https://fetch.spec.whatwg.org/#header-name
	*/
	function isValidHeaderName(value) {
		if (typeof value !== "string") return false;
		if (value.length === 0) return false;
		for (let i = 0; i < value.length; i++) {
			const character = value.charCodeAt(i);
			if (character > 127 || !isToken(character)) return false;
		}
		return true;
	}
	function isToken(value) {
		return ![
			127,
			32,
			"(",
			")",
			"<",
			">",
			"@",
			",",
			";",
			":",
			"\\",
			"\"",
			"/",
			"[",
			"]",
			"?",
			"=",
			"{",
			"}"
		].includes(value);
	}
	/**
	* Validate the given header value.
	* @see https://fetch.spec.whatwg.org/#header-value
	*/
	function isValidHeaderValue(value) {
		if (typeof value !== "string") return false;
		if (value.trim() !== value) return false;
		for (let i = 0; i < value.length; i++) {
			const character = value.charCodeAt(i);
			if (character === 0 || character === 10 || character === 13) return false;
		}
		return true;
	}
	let _Symbol$toStringTag;
	const NORMALIZED_HEADERS = Symbol("normalizedHeaders");
	const RAW_HEADER_NAMES = Symbol("rawHeaderNames");
	const HEADER_VALUE_DELIMITER = ", ";
	var Headers$1 = class Headers {
		constructor(init) {
			this[NORMALIZED_HEADERS] = {};
			this[RAW_HEADER_NAMES] = /* @__PURE__ */ new Map();
			this[_Symbol$toStringTag] = "Headers";
			/**
			* @note Cannot necessarily check if the `init` is an instance of the
			* `Headers` because that class may not be defined in Node or jsdom.
			*/
			if (["Headers", "HeadersPolyfill"].includes(init?.constructor?.name) || init instanceof Headers || typeof globalThis.Headers !== "undefined" && init instanceof globalThis.Headers) init.forEach((value, name) => {
				this.append(name, value);
			}, this);
			else if (Array.isArray(init)) init.forEach(([name, value]) => {
				this.append(name, Array.isArray(value) ? value.join(HEADER_VALUE_DELIMITER) : value);
			});
			else if (init) Object.getOwnPropertyNames(init).forEach((name) => {
				const value = init[name];
				this.append(name, Array.isArray(value) ? value.join(HEADER_VALUE_DELIMITER) : value);
			});
		}
		[(_Symbol$toStringTag = Symbol.toStringTag, Symbol.iterator)]() {
			return this.entries();
		}
		*keys() {
			for (const [name] of this.entries()) yield name;
		}
		*values() {
			for (const [, value] of this.entries()) yield value;
		}
		*entries() {
			let sortedKeys = Object.keys(this[NORMALIZED_HEADERS]).sort((a, b) => a.localeCompare(b));
			for (const name of sortedKeys) if (name === "set-cookie") for (const value of this.getSetCookie()) yield [name, value];
			else yield [name, this.get(name)];
		}
		/**
		* Returns a boolean stating whether a `Headers` object contains a certain header.
		*/
		has(name) {
			if (!isValidHeaderName(name)) throw new TypeError(`Invalid header name "${name}"`);
			return this[NORMALIZED_HEADERS].hasOwnProperty(normalizeHeaderName(name));
		}
		/**
		* Returns a `ByteString` sequence of all the values of a header with a given name.
		*/
		get(name) {
			if (!isValidHeaderName(name)) throw TypeError(`Invalid header name "${name}"`);
			return this[NORMALIZED_HEADERS][normalizeHeaderName(name)] ?? null;
		}
		/**
		* Sets a new value for an existing header inside a `Headers` object, or adds the header if it does not already exist.
		*/
		set(name, value) {
			if (!isValidHeaderName(name) || !isValidHeaderValue(value)) return;
			const normalizedName = normalizeHeaderName(name);
			const normalizedValue = normalizeHeaderValue(value);
			this[NORMALIZED_HEADERS][normalizedName] = normalizeHeaderValue(normalizedValue);
			this[RAW_HEADER_NAMES].set(normalizedName, name);
		}
		/**
		* Appends a new value onto an existing header inside a `Headers` object, or adds the header if it does not already exist.
		*/
		append(name, value) {
			if (!isValidHeaderName(name) || !isValidHeaderValue(value)) return;
			const normalizedName = normalizeHeaderName(name);
			const normalizedValue = normalizeHeaderValue(value);
			let resolvedValue = this.has(normalizedName) ? `${this.get(normalizedName)}, ${normalizedValue}` : normalizedValue;
			this.set(name, resolvedValue);
		}
		/**
		* Deletes a header from the `Headers` object.
		*/
		delete(name) {
			if (!isValidHeaderName(name)) return;
			if (!this.has(name)) return;
			const normalizedName = normalizeHeaderName(name);
			delete this[NORMALIZED_HEADERS][normalizedName];
			this[RAW_HEADER_NAMES].delete(normalizedName);
		}
		/**
		* Traverses the `Headers` object,
		* calling the given callback for each header.
		*/
		forEach(callback, thisArg) {
			for (const [name, value] of this.entries()) callback.call(thisArg, value, name, this);
		}
		/**
		* Returns an array containing the values
		* of all Set-Cookie headers associated
		* with a response
		*/
		getSetCookie() {
			const setCookieHeader = this.get("set-cookie");
			if (setCookieHeader === null) return [];
			if (setCookieHeader === "") return [""];
			return splitCookiesString(setCookieHeader);
		}
	};
	/**
	* Converts a string representation of headers (i.e. from XMLHttpRequest)
	* to a new `Headers` instance.
	*/
	function stringToHeaders(str) {
		return str.trim().split(/[\r\n]+/).reduce((headers, line) => {
			if (line.trim() === "") return headers;
			const parts = line.split(": ");
			const name = parts.shift();
			const value = parts.join(": ");
			headers.append(name, value);
			return headers;
		}, new Headers$1());
	}
	//#endregion
	//#region src/core/utils/internal/parse-multipart-data.ts
	function parseContentHeaders(headersString) {
		const headers = stringToHeaders(headersString);
		const contentType = headers.get("content-type") || "text/plain";
		const disposition = headers.get("content-disposition");
		if (!disposition) throw new Error("\"Content-Disposition\" header is required.");
		const directives = disposition.split(";").reduce((acc, chunk) => {
			const [name, ...rest] = chunk.trim().split("=");
			acc[name] = rest.join("=");
			return acc;
		}, {});
		return {
			name: directives.name?.slice(1, -1),
			filename: directives.filename?.slice(1, -1),
			contentType
		};
	}
	/**
	* Parses a given string as a multipart/form-data.
	* Does not throw an exception on an invalid multipart string.
	*/
	function parseMultipartData(data, headers) {
		const contentType = headers?.get("content-type");
		if (!contentType) return;
		const [, ...directives] = contentType.split(/; */);
		const boundary = directives.filter((d) => d.startsWith("boundary=")).map((s) => s.replace(/^boundary=/, ""))[0];
		if (!boundary) return;
		const boundaryRegExp = new RegExp(`--+${boundary.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
		const fields = data.split(boundaryRegExp).filter((chunk) => chunk.startsWith("\r\n") && chunk.endsWith("\r\n")).map((chunk) => chunk.trimStart().replace(/\r\n$/, ""));
		if (!fields.length) return;
		const parsedBody = {};
		try {
			for (const field of fields) {
				const [contentHeaders, ...rest] = field.split("\r\n\r\n");
				const contentBody = rest.join("\r\n\r\n");
				const { contentType, filename, name } = parseContentHeaders(contentHeaders);
				const value = filename === void 0 ? contentBody : new File([contentBody], filename, { type: contentType });
				const parsedValue = parsedBody[name];
				if (parsedValue === void 0) parsedBody[name] = value;
				else if (Array.isArray(parsedValue)) parsedBody[name] = [...parsedValue, value];
				else parsedBody[name] = [parsedValue, value];
			}
			return parsedBody;
		} catch {
			return;
		}
	}
	//#endregion
	//#region src/graphql/parse-graphql-request.ts
	function parseDocumentNode(node, operationName) {
		const operationDefs = node.definitions.filter((definition) => {
			return definition.kind === "OperationDefinition";
		});
		/**
		* @note A document may bundle multiple operations (e.g. the ones
		* emitted by GraphQL Code Generator). Honor the requested operation
		* name, and resolve nothing if the document has no such operation.
		* Falling back to the first operation would silently resolve one the
		* client never asked for.
		*/
		const operationDef = operationName ? operationDefs.find((definition) => {
			return definition.name?.value === operationName;
		}) : operationDefs[0];
		return {
			operationType: operationDef?.operation,
			/**
			* @note Echo the requested operation name even when the document
			* has no such operation. It makes the "unhandled operation" warnings
			* name the operation the client actually asked for.
			*/
			operationName: operationDef?.name?.value || operationName || void 0
		};
	}
	async function parseQuery(query, operationName) {
		try {
			return parseDocumentNode(parse(query), operationName);
		} catch (error) {
			return error;
		}
	}
	function extractMultipartVariables(variables, map, files) {
		const operations = { variables };
		for (const [key, pathArray] of Object.entries(map)) {
			if (!(key in files)) throw new Error(`Given files do not have a key '${key}' .`);
			for (const dotPath of pathArray) {
				const [lastPath, ...reversedPaths] = dotPath.split(".").reverse();
				const paths = reversedPaths.reverse();
				let target = operations;
				for (const path of paths) {
					if (!(path in target)) throw new Error(`Property '${path}' is not in operations.`);
					target = target[path];
				}
				target[lastPath] = files[key];
			}
		}
		return operations.variables;
	}
	async function getGraphQLInput(request) {
		switch (request.method) {
			case "GET": {
				const url = new URL(request.url);
				return {
					query: url.searchParams.get("query"),
					variables: jsonParse(url.searchParams.get("variables") || ""),
					operationName: url.searchParams.get("operationName")
				};
			}
			case "POST": {
				const requestClone = request.clone();
				if (request.headers.get("content-type")?.includes("multipart/form-data")) {
					const responseJson = parseMultipartData(await requestClone.text(), request.headers);
					if (!responseJson) return null;
					const { operations, map, ...files } = responseJson;
					const parsedOperations = jsonParse(operations) || {};
					if (!parsedOperations.query) return null;
					const parsedMap = jsonParse(map || "") || {};
					const variables = parsedOperations.variables ? extractMultipartVariables(parsedOperations.variables, parsedMap, files) : {};
					return {
						query: parsedOperations.query,
						variables,
						operationName: parsedOperations.operationName
					};
				}
				const requestJson = await requestClone.json().catch(() => null);
				if (requestJson?.query) {
					const { query, variables, operationName } = requestJson;
					return {
						query,
						variables,
						operationName
					};
				}
				return null;
			}
			default: return null;
		}
	}
	/**
	* Determines if a given request can be considered a GraphQL request.
	* Does not parse the query and does not guarantee its validity.
	*/
	async function parseGraphQLRequest(request) {
		const input = await getGraphQLInput(request);
		if (!input || !input.query) return;
		const { query, variables, operationName } = input;
		const parsedResult = await parseQuery(query, operationName);
		if (parsedResult instanceof Error) {
			const requestPublicUrl = toPublicUrl(request.url);
			throw new Error(devUtils.formatMessage("Failed to intercept a GraphQL request to \"%s %s\": cannot parse query. See the error message from the parser below.\n\n%s", request.method, requestPublicUrl, parsedResult.message));
		}
		return {
			query: input.query,
			operationType: parsedResult.operationType,
			operationName: parsedResult.operationName,
			variables
		};
	}
	//#endregion
	//#region src/core/utils/request/get-all-accepted-mime-types.ts
	/**
	* Returns all accepted mime types, ordered by precedence as defined
	* in [RFC 7231 Section 5.3.2](https://datatracker.ietf.org/doc/html/rfc7231#section-5.3.2).
	*
	* Precedence rules (highest to lowest):
	* 1. Quality value (`q` parameter, default 1).
	* 2. Specificity: `type/subtype` > `type/*` > `*\/*`.
	* 3. Number of media type parameters (more = more specific).
	*
	* Types with `q=0` are excluded (explicitly not acceptable).
	*/
	function getAllAcceptedMimeTypes(acceptHeader) {
		if (acceptHeader == null) return [];
		const accepted = [];
		for (const part of acceptHeader.split(",")) {
			const [type, ...params] = part.split(";").map((v) => v.trim());
			let quality = 1;
			let parameterCount = 0;
			for (const param of params) {
				const [key, value] = param.split("=").map((v) => v.trim());
				if (key === "q") quality = Number(value);
				else parameterCount++;
			}
			if (quality === 0) continue;
			const [mediaType, mediaSubtype] = type.split("/");
			const specificity = mediaType === "*" ? 0 : mediaSubtype === "*" ? 1 : 2;
			accepted.push({
				type,
				quality,
				specificity,
				parameterCount
			});
		}
		if (!accepted.length) return [];
		return accepted.sort((left, right) => {
			if (right.quality !== left.quality) return right.quality - left.quality;
			if (right.specificity !== left.specificity) return right.specificity - left.specificity;
			return right.parameterCount - left.parameterCount;
		}).map((entry) => entry.type);
	}
	//#endregion
	//#region src/graphql/graphql-handler.ts
	function isDocumentNode(value) {
		if (value == null) return false;
		return typeof value === "object" && "kind" in value && "definitions" in value;
	}
	function isDocumentTypeDecoration(value) {
		return value instanceof String;
	}
	var GraphQLHandler = class GraphQLHandler extends RequestHandler {
		endpoint;
		static parsedRequestCache = /* @__PURE__ */ new WeakMap();
		static #parseOperationName(predicate, operationType) {
			const getOperationName = (node) => {
				invariant$1(node.operationType === operationType, "Failed to create a GraphQL handler: provided a DocumentNode with a mismatched operation type (expected \"%s\" but got \"%s\").", operationType, node.operationType);
				invariant$1(node.operationName, "Failed to create a GraphQL handler: provided a DocumentNode without operation name");
				return node.operationName;
			};
			if (isDocumentNode(predicate)) return getOperationName(parseDocumentNode(predicate));
			if (isDocumentTypeDecoration(predicate)) {
				const documentNode = parse(predicate.toString());
				invariant$1(isDocumentNode(documentNode), "Failed to create a GraphQL handler: given TypedDocumentString (%s) does not produce a valid DocumentNode", predicate);
				return getOperationName(parseDocumentNode(documentNode));
			}
			return predicate;
		}
		/**
		* Creates a GraphQL handler information object from the given
		* operation predicate. Normalizes `DocumentNode` and typed document
		* string predicates to plain operation names.
		*/
		static parseGraphQLRequestInfo(args) {
			const operationName = GraphQLHandler.#parseOperationName(args.predicate, args.operationType);
			const displayOperationName = typeof operationName === "function" ? "[custom predicate]" : operationName;
			return {
				header: args.operationType === "all" ? `${args.operationType} (origin: ${args.url.toString()})` : `${args.operationType}${displayOperationName ? ` ${displayOperationName}` : ""} (origin: ${args.url.toString()})`,
				operationType: args.operationType,
				operationName
			};
		}
		constructor(operationType, predicate, endpoint, resolver, options) {
			super({
				info: GraphQLHandler.parseGraphQLRequestInfo({
					operationType,
					predicate,
					url: endpoint
				}),
				resolver,
				options
			});
			this.endpoint = endpoint;
		}
		/**
		* Parses the request body, once per request, cached across all
		* GraphQL handlers. This is done to avoid multiple parsing of the
		* request body, which each requires a clone of the request.
		*/
		async parseGraphQLRequestOrGetFromCache(request) {
			if (!GraphQLHandler.parsedRequestCache.has(request)) GraphQLHandler.parsedRequestCache.set(request, await parseGraphQLRequest(request).catch((error) => {
				console.error(error);
			}));
			return GraphQLHandler.parsedRequestCache.get(request);
		}
		async parse(args) {
			const match = matchRequestUrl(new URL(args.request.url), this.endpoint);
			const cookies = getAllRequestCookies(args.request);
			if (!match.matches) return {
				match,
				cookies
			};
			const parsedResult = await this.parseGraphQLRequestOrGetFromCache(args.request);
			if (typeof parsedResult === "undefined") return {
				match,
				cookies
			};
			return {
				match,
				cookies,
				query: parsedResult.query,
				operationType: parsedResult.operationType,
				operationName: parsedResult.operationName,
				variables: parsedResult.variables
			};
		}
		async predicate(args) {
			if (args.parsedResult.operationType === void 0) return false;
			if (!args.parsedResult.operationName && this.info.operationType !== "all") {
				const publicUrl = toPublicUrl(args.request.url);
				devUtils.warn(`\
Failed to intercept a GraphQL request at "${args.request.method} ${publicUrl}": anonymous GraphQL operations are not supported.

Consider naming this operation or using the "operation()" request handler of "graphql.link()" to intercept GraphQL requests regardless of their operation name/type. Read more: https://mswjs.io/docs/api/graphql/#graphqloperationresolver`);
				return false;
			}
			const hasMatchingOperationType = this.info.operationType === "all" || args.parsedResult.operationType === this.info.operationType;
			/**
			* Check if the operation name matches the outgoing GraphQL request.
			* @note Unlike the HTTP handler, the custom predicate functions are invoked
			* during predicate, not parsing, because GraphQL request parsing happens first,
			* and non-GraphQL requests are filtered out automatically.
			*/
			const hasMatchingOperationName = await this.matchOperationName({
				request: args.request,
				parsedResult: args.parsedResult
			});
			return args.parsedResult.match.matches && hasMatchingOperationType && hasMatchingOperationName;
		}
		async run(args) {
			const result = await super.run(args);
			if (result?.response == null) return result;
			if (!(kDefaultContentType in result.response)) return result;
			const acceptedMimeTypes = getAllAcceptedMimeTypes(args.request.headers.get("accept"));
			if (acceptedMimeTypes.length === 0) return result;
			const graphqlResponseIndex = acceptedMimeTypes.indexOf("application/graphql-response+json");
			const jsonIndex = acceptedMimeTypes.indexOf("application/json");
			/**
			* Use the "application/graphql-response+json" response content type
			* only when the client accepts it AND prefers it over "application/json"
			* (i.e. it appears earlier in the precedence-sorted list, or "application/json"
			* is not listed at all).
			* @see https://github.com/graphql/graphql-over-http/blob/4d1df1fb829ec2dd3ecbf3c6aa4025bd356c270d/spec/GraphQLOverHTTP.md#accept
			*/
			if (graphqlResponseIndex !== -1 && (jsonIndex === -1 || graphqlResponseIndex <= jsonIndex)) result.response.headers.set("content-type", "application/graphql-response+json");
			return result;
		}
		async matchOperationName(args) {
			if (typeof this.info.operationName === "function") {
				const customPredicateResult = await this.info.operationName({
					request: args.request,
					...this.extendResolverArgs({
						request: args.request,
						parsedResult: args.parsedResult
					})
				});
				/**
				* @note Keep the { matches } signature in case we decide to support path parameters
				* in GraphQL handlers. If that happens, the custom predicate would have to be moved
				* to the parsing phase, the same as we have for the HttpHandler, and the user will
				* have a possibility to return parsed path parameters from the custom predicate.
				*/
				return typeof customPredicateResult === "boolean" ? customPredicateResult : customPredicateResult.matches;
			}
			if (this.info.operationName instanceof RegExp) return this.info.operationName.test(args.parsedResult.operationName || "");
			return args.parsedResult.operationName === this.info.operationName;
		}
		extendResolverArgs(args) {
			return {
				query: args.parsedResult.query || "",
				operationType: args.parsedResult.operationType,
				operationName: args.parsedResult.operationName || "",
				variables: args.parsedResult.variables || {},
				cookies: args.parsedResult.cookies
			};
		}
		async log(args) {
			const loggedRequest = await serializeRequest(args.request);
			const loggedResponse = await serializeResponse(args.response);
			const statusColor = getStatusCodeColor(loggedResponse.status);
			const requestInfo = args.parsedResult.operationName ? `${args.parsedResult.operationType} ${args.parsedResult.operationName}` : `anonymous ${args.parsedResult.operationType}`;
			console.groupCollapsed(devUtils.formatMessage(`${getTimestamp()} ${requestInfo} (%c${loggedResponse.status} ${loggedResponse.statusText}%c)`), `color:${statusColor}`, "color:inherit");
			console.log("Request:", loggedRequest);
			console.log("Handler:", this);
			console.log("Response:", loggedResponse);
			console.groupEnd();
		}
	};
	//#endregion
	//#region src/graphql/graphql-subscription-event.ts
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
	var GraphQLSubscriptionEvent = class extends TypedEvent {
		operationName;
		query;
		variables;
		request;
		constructor(init) {
			super("graphql:subscription");
			this.operationName = init.operationName;
			this.query = init.query;
			this.variables = init.variables;
			this.request = init.request;
		}
	};
	//#endregion
	//#region src/graphql/graphql-subscription.ts
	function createInitMessage(payload) {
		return JSON.stringify({
			type: "connection_init",
			payload
		});
	}
	function createAcknowledgeMessage() {
		return JSON.stringify({ type: "connection_ack" });
	}
	function createNextMessage(args) {
		return JSON.stringify({
			id: args.id,
			type: "next",
			payload: args.payload
		});
	}
	function createErrorMessage(args) {
		return JSON.stringify({
			id: args.id,
			type: "error",
			payload: args.payload
		});
	}
	function createCompleteMessage(args) {
		return JSON.stringify({
			id: args.id,
			type: "complete"
		});
	}
	function createPongMessage() {
		return JSON.stringify({ type: "pong" });
	}
	/**
	* Construct a request representing the WebSocket upgrade of the given
	* connection. GraphQL subscriptions have no request of their own, so
	* this describes the connection they are multiplexed over.
	*/
	function createUpgradeRequest(url) {
		return new Request(url, { headers: {
			connection: "upgrade",
			upgrade: "websocket"
		} });
	}
	function parseGraphQLWebSocketMessage(data) {
		if (typeof data !== "string") return;
		const message = jsonParse(data);
		if (!message || typeof message.type !== "string") return;
		return message;
	}
	/**
	* Connect to the original server and initialize the `graphql-transport-ws`
	* session for the given connection, at most once.
	*
	* @note The server connection is shared by every subscription of this
	* client. Initializing it more than once makes a compliant GraphQL server
	* close it ("Too many initialisation requests").
	*/
	function ensureUpstreamSession(connection) {
		if (connection.upstreamSession) return connection.upstreamSession;
		const { server } = connection;
		connection.upstreamSession = new Promise((resolve) => {
			server.addEventListener("message", (event) => {
				if (parseGraphQLWebSocketMessage(event.data)?.type === "connection_ack") {
					event.preventDefault();
					resolve();
				}
			});
			server.addEventListener("open", () => {
				server.send(createInitMessage(connection.connectionParams));
			}, { once: true });
			server.connect();
		});
		return connection.upstreamSession;
	}
	/**
	* The `graphql-transport-ws` sessions of the intercepted WebSocket
	* connections, keyed by the client id.
	*
	* @note This registry is module-level, and not per-transport, on purpose.
	* Multiple `graphql.link()` calls to the same endpoint create multiple
	* transports, and all of them must share a single session per connection.
	* Otherwise, each transport binds its own protocol listeners to the same
	* client, which makes it receive duplicate `connection_ack`/`pong` frames
	* and resolves matching subscription handlers more than once.
	*/
	const connections = /* @__PURE__ */ new Map();
	/**
	* The WebSocket protocol implemented by the subscription transport.
	* @see https://github.com/graphql/graphql-over-http/blob/main/rfcs/GraphQLOverWebSocket.md
	*/
	const GRAPHQL_WEBSOCKET_SUBPROTOCOL = "graphql-transport-ws";
	function includesGraphQLProtocol(protocols) {
		if (protocols == null) return false;
		return (typeof protocols === "string" ? protocols.split(",") : protocols).some((protocol) => {
			return protocol.trim() === GRAPHQL_WEBSOCKET_SUBPROTOCOL;
		});
	}
	/**
	* A WebSocket handler that only matches connections that requested the
	* `graphql-transport-ws` protocol. Connections without it (e.g.
	* arbitrary non-GraphQL WebSockets whose URL matched a permissive
	* endpoint like a wildcard link) are left unhandled so they follow the
	* regular unhandled connection flow (warnings, passthrough).
	*/
	var GraphQLWebSocketHandler = class extends WebSocketHandler {
		async run(connection, resolutionContext) {
			if (!includesGraphQLProtocol(connection.info.protocols)) return null;
			return super.run(connection, resolutionContext);
		}
	};
	/**
	* A WebSocket handler implementing the `graphql-transport-ws` protocol
	* session for a single GraphQL endpoint. One transport is shared across
	* all subscription handlers created from the same `graphql.link()` call
	* (attached to each of them as a sibling handler).
	*
	* The transport owns the protocol/session concerns: connection
	* acknowledgement, keep-alive, the per-connection registry of active
	* subscriptions, and dispatching parsed `subscribe` operations to the
	* matching subscription handler.
	*/
	var GraphQLSubscriptionTransportHandler = class extends GraphQLWebSocketHandler {
		/**
		* Register the given handler as a subscriber to the GraphQL
		* subscriptions on the given WebSocket connection. Subscribers are
		* dispatched in registration order, which follows the handlers
		* resolution order (runtime handlers take precedence).
		*/
		subscribe(connection, handler, subscriber) {
			this.#getOrCreateConnection(connection).subscribers.set(handler, {
				transport: this,
				subscriber
			});
		}
		getConnection(clientId) {
			return connections.get(clientId);
		}
		async run(connection, resolutionContext) {
			const handlerConnection = await super.run(connection, resolutionContext);
			if (handlerConnection) {
				const transportConnection = this.#getOrCreateConnection(handlerConnection);
				if (resolutionContext?.events) transportConnection.events = resolutionContext.events;
			}
			return handlerConnection;
		}
		/**
		* End the given subscription without notifying the client. Used when
		* the subscription has already been terminated over the wire (e.g. the
		* original server completed it and that frame reached the client).
		*/
		endSubscription(args) {
			const connection = connections.get(args.clientId);
			if (connection) this.#endSubscription(connection, args.subscriptionId);
		}
		/**
		* Schedule a cleanup to run once the given subscription ends.
		*
		* @note If the subscription has already ended by the time this is
		* called, the cleanup runs immediately. The resolver can no longer
		* affect that subscription, so there is nothing left to wait for.
		*/
		finalize(args) {
			const cleanups = connections.get(args.clientId)?.subscriptions.get(args.subscriptionId);
			if (cleanups) {
				cleanups.push(args.cleanup);
				return;
			}
			this.#exhaustCleanups([args.cleanup]);
		}
		async #endAllSubscriptions(connection) {
			const pendingCleanups = [];
			for (const subscriptionId of connection.subscriptions.keys()) pendingCleanups.push(this.#endSubscription(connection, subscriptionId));
			await Promise.all(pendingCleanups);
		}
		/**
		* End the given subscription and run the cleanups scheduled for it.
		*
		* This is the single exit point for every way a subscription can end:
		* completed by the mock, by the client, or by the original server;
		* terminated with errors; dropped when the client disconnects; or
		* detached from its resolver when the handlers are reset. Ending an
		* already-ended subscription is a no-op, so the cleanups are
		* guaranteed to run at most once.
		*/
		#endSubscription(connection, subscriptionId) {
			const cleanups = connection.subscriptions.get(subscriptionId);
			if (!cleanups) return Promise.resolve();
			connection.subscriptions.delete(subscriptionId);
			return this.#exhaustCleanups(cleanups);
		}
		/**
		* Run the given cleanups as LIFO, consistently with `finalize()` in
		* the request handlers. Cleanups are detached from the subscription
		* life-cycle: nothing awaits them, so this must never reject.
		*/
		async #exhaustCleanups(cleanups) {
			const errors = [];
			for (let index = cleanups.length - 1; index >= 0; index--) try {
				await cleanups[index]();
			} catch (error) {
				if (error instanceof Error) errors.push(error);
			}
			if (errors.length > 0) devUtils.error("Failed to execute the cleanup for a GraphQL subscription to \"%s\". Please see the original error below.", this.url.toString(), new AggregateError(errors));
		}
		/**
		* Send a `next` message with the given payload to the subscription.
		*/
		publish(args) {
			const connection = this.#getConnectionForSubscription({
				clientId: args.clientId,
				subscriptionId: args.subscriptionId,
				intent: "publish to"
			});
			if (!connection) return;
			connection.client.send(createNextMessage({
				id: args.subscriptionId,
				payload: args.payload
			}));
		}
		/**
		* Send a terminal `error` message to the subscription and
		* removes it from the registry of active subscriptions.
		*/
		error(args) {
			const connection = this.#getConnectionForSubscription({
				clientId: args.clientId,
				subscriptionId: args.subscriptionId,
				intent: "error"
			});
			if (!connection) return;
			connection.client.send(createErrorMessage({
				id: args.subscriptionId,
				payload: args.errors
			}));
			this.#endSubscription(connection, args.subscriptionId);
		}
		/**
		* Send a `complete` message to the subscription and removes it
		* from the registry of active subscriptions.
		*/
		complete(args) {
			const connection = this.#getConnectionForSubscription({
				clientId: args.clientId,
				subscriptionId: args.subscriptionId,
				intent: "complete"
			});
			if (!connection) return;
			connection.client.send(createCompleteMessage({ id: args.subscriptionId }));
			this.#endSubscription(connection, args.subscriptionId);
		}
		/**
		* Drop this transport's subscribers and active subscriptions from the
		* sessions it participates in. The sessions themselves are left intact:
		* they are shared with the other transports of the same connection and
		* own the protocol listeners for as long as the client stays connected.
		*
		* @note This method is invoked automatically when the handlers
		* controller resets the handlers (e.g. `server.resetHandlers()`).
		*/
		reset() {
			for (const connection of connections.values()) {
				let ownsConnection = false;
				for (const [handler, entry] of connection.subscribers) if (entry.transport === this) {
					connection.subscribers.delete(handler);
					ownsConnection = true;
				}
				if (ownsConnection) this.#endAllSubscriptions(connection);
			}
		}
		/**
		* Forget the sessions of this transport, ending their subscriptions.
		* @note This method is invoked automatically when the network is
		* disabled (e.g. `server.close()`).
		*/
		dispose() {
			const pendingCleanups = [];
			for (const [clientId, connection] of connections) {
				for (const [handler, entry] of connection.subscribers) if (entry.transport === this) connection.subscribers.delete(handler);
				if (connection.subscribers.size === 0) {
					pendingCleanups.push(this.#endAllSubscriptions(connection));
					connections.delete(clientId);
				}
			}
			if (pendingCleanups.length > 0) return Promise.all(pendingCleanups).then(() => {});
		}
		/**
		* @note The transport is the sole owner of logging for GraphQL
		* subscription connections. It logs parsed `graphql-transport-ws`
		* frames instead of raw WebSocket messages.
		*/
		log(connection) {
			return attachGraphQLSubscriptionLogger(connection);
		}
		[kConnect](connection) {
			this.#getOrCreateConnection(connection);
			return true;
		}
		#getOrCreateConnection(connection) {
			const { client } = connection;
			const existingConnection = connections.get(client.id);
			if (existingConnection) return existingConnection;
			const transportConnection = {
				client: connection.client,
				server: connection.server,
				subscribers: /* @__PURE__ */ new Map(),
				subscriptions: /* @__PURE__ */ new Map()
			};
			connections.set(client.id, transportConnection);
			client.addEventListener("message", (event) => {
				this.#handleClientMessage(client.id, event.data);
			});
			client.addEventListener("close", () => {
				this.#endAllSubscriptions(transportConnection);
				connections.delete(client.id);
			});
			return transportConnection;
		}
		#getConnectionForSubscription(args) {
			const connection = connections.get(args.clientId);
			if (!connection || !connection.subscriptions.has(args.subscriptionId)) {
				devUtils.warn("Failed to %s the GraphQL subscription \"%s\": the subscription is no longer active.", args.intent, args.subscriptionId);
				return;
			}
			return connection;
		}
		#handleClientMessage(clientId, data) {
			const connection = connections.get(clientId);
			if (!connection) return;
			const message = parseGraphQLWebSocketMessage(data);
			if (!message) return;
			switch (message.type) {
				case "connection_init":
					connection.connectionParams = message.payload;
					connection.client.send(createAcknowledgeMessage());
					break;
				case "ping":
					connection.client.send(createPongMessage());
					break;
				case "subscribe":
					this.#handleSubscribeMessage(connection, message);
					break;
				case "complete": this.#endSubscription(connection, message.id);
			}
		}
		#handleSubscribeMessage(connection, message) {
			let node;
			try {
				node = parseDocumentNode(parse(message.payload.query), message.payload.operationName);
			} catch (error) {
				devUtils.warn("Failed to intercept a GraphQL subscription to \"%s\": the subscription query is not a valid GraphQL document.\n\n%s", toPublicUrl(connection.client.url), error);
				return;
			}
			if (node.operationType !== OperationTypeNode.SUBSCRIPTION) {
				devUtils.warn("Intercepted a GraphQL %s \"%s\" over WebSocket: only subscription operations are supported over the WebSocket transport.", node.operationType, node.operationName || "(anonymous)");
				return;
			}
			connection.subscriptions.set(message.id, []);
			for (const { subscriber } of connection.subscribers.values()) if (subscriber({
				node,
				message
			})) {
				this.#emitSubscriptionEvent(connection, node, message);
				return;
			}
			devUtils.warn("Intercepted a GraphQL subscription \"%s\" to \"%s\" that has no matching subscription handler. If you wish to mock this subscription, create a subscription handler for it.", node.operationName || "(anonymous)", toPublicUrl(connection.client.url));
		}
		/**
		* Emit the "graphql:subscription" life-cycle event on the network.
		* The event is emitted once the subscription has been established:
		* matched by a subscription handler and resolved.
		*/
		#emitSubscriptionEvent(connection, node, message) {
			if (!connection.events || !node.operationName) return;
			connection.events.emit(new GraphQLSubscriptionEvent({
				operationName: node.operationName,
				query: message.payload.query,
				variables: { ...message.payload.variables },
				request: createUpgradeRequest(connection.client.url)
			}));
		}
	};
	/**
	* A WebSocket handler intercepting GraphQL subscriptions by their
	* operation name. Matching and resolution are delegated to it by the
	* subscription transport (its sibling handler) so the first matching
	* handler wins, respecting runtime handler overrides.
	*/
	var GraphQLSubscriptionHandler = class extends GraphQLWebSocketHandler {
		info;
		isUsed;
		#operationName;
		#transport;
		#resolver;
		#options;
		constructor(args) {
			super(args.url);
			this.info = GraphQLHandler.parseGraphQLRequestInfo({
				operationType: OperationTypeNode.SUBSCRIPTION,
				predicate: args.operationName,
				url: args.url
			});
			const { operationName } = this.info;
			invariant$1(typeof operationName !== "function" && !isDocumentNode(operationName), "Failed to create a GraphQL subscription handler: custom predicates are not supported for subscriptions");
			this.#operationName = operationName;
			this.#transport = args.transport;
			this.#resolver = args.resolver;
			this.#options = args.options || {};
			this.isUsed = false;
		}
		reset() {
			this.isUsed = false;
		}
		/**
		* @note Individual subscription handlers stay silent. The subscription
		* transport owns the GraphQL-aware logging for the entire connection
		* (a logger is attached once per matching handler otherwise).
		*/
		log() {
			return function detachLogger() {};
		}
		[kConnect](connection) {
			this.#transport.subscribe(connection, this, (args) => {
				return this.#handleSubscribe(connection, args);
			});
			return true;
		}
		#handleSubscribe(connection, args) {
			if (this.#options.once && this.isUsed) return false;
			const { operationName } = args.node;
			if (!operationName || !this.#matchesOperationName(operationName)) return false;
			this.isUsed = true;
			const subscription = new GraphQLSubscription({
				message: args.message,
				clientId: connection.client.id,
				transport: this.#transport
			});
			this.#resolver({
				params: connection.params,
				operationName,
				subscription,
				request: createUpgradeRequest(connection.client.url),
				finalize: (cleanup) => {
					this.#transport.finalize({
						clientId: connection.client.id,
						subscriptionId: subscription.id,
						cleanup
					});
				}
			});
			return true;
		}
		#matchesOperationName(operationName) {
			if (this.#operationName instanceof RegExp) return this.#operationName.test(operationName);
			return this.#operationName === operationName;
		}
	};
	/**
	* Representation of the intercepted GraphQL subscription.
	*/
	var GraphQLSubscription = class {
		id;
		query;
		variables;
		extensions;
		#message;
		#clientId;
		#transport;
		constructor(args) {
			this.id = args.message.id;
			this.query = args.message.payload.query;
			this.variables = args.message.payload.variables || {};
			this.extensions = args.message.payload.extensions;
			this.#message = args.message;
			this.#clientId = args.clientId;
			this.#transport = args.transport;
		}
		/**
		* Publish an execution result to the subscribed client.
		*
		* @example
		* subscription.publish({
		*   data: {
		*     postAdded: {
		*       id: 'abc-123'
		*     }
		*   }
		* })
		*/
		publish(payload) {
			this.#transport.publish({
				clientId: this.#clientId,
				subscriptionId: this.id,
				payload
			});
		}
		/**
		* Use the given `Iterable` or `AsyncIterable` as the source
		* of data for this subscription. Whenever the iterable yields a
		* value, it gets published to this subscription.
		*
		* @example
		* subscription.from(async function* () {
		*   yield { text: 'hello world' }
		* })
		*/
		async from(source) {
			for await (const data of source) this.publish({ data });
		}
		/**
		* Terminate this subscription with the given errors.
		*
		* @example
		* subscription.error([{ message: 'Something went wrong' }])
		*/
		error(errors) {
			this.#transport.error({
				clientId: this.#clientId,
				subscriptionId: this.id,
				errors
			});
		}
		/**
		* Marks this subscription as complete.
		*
		* @example
		* subscription.complete()
		*/
		complete() {
			this.#transport.complete({
				clientId: this.#clientId,
				subscriptionId: this.id
			});
		}
		/**
		* Perform this GraphQL subscription as-is.
		* This establishes a connection to the actual server, replays
		* the intercepted subscription, and forwards the server payloads
		* to the GraphQL client. You can intercept, modify, or prevent
		* any of the original server messages.
		*
		* @example
		* const postAddedSubscription = subscription.passthrough()
		* postAddedSubscription.addEventListener('next', (event) => {
		*   event.preventDefault()
		*   event.data.payload.data.postAdded.id = 'mock-id'
		*   subscription.publish(event.data.payload)
		* })
		*/
		passthrough() {
			const connection = this.#transport.getConnection(this.#clientId);
			/**
			* @note One can only call this method inside the GraphQL subscription
			* handler. By that point, the WebSocket connection has been established
			* and intercepted so the connection reference is guaranteed.
			*/
			invariant$1(connection, "Failed to passthrough the GraphQL subscription (\"%s\"): the underlying WebSocket connection is closed", this.query);
			return new GraphQLPassthroughSubscription({
				server: connection.server,
				message: this.#message,
				upstreamSession: ensureUpstreamSession(connection),
				onTerminate: () => {
					this.#transport.endSubscription({
						clientId: this.#clientId,
						subscriptionId: this.id
					});
				}
			});
		}
	};
	/**
	* Representation of a GraphQL subscription to the actual server.
	* You interface with this object from the client's perspective.
	*/
	var GraphQLPassthroughSubscription = class {
		#server;
		#message;
		#emitter;
		#abortController;
		#onTerminate;
		constructor(args) {
			this.#server = args.server;
			this.#message = args.message;
			this.#onTerminate = args.onTerminate;
			this.#emitter = new Emitter();
			this.#abortController = new AbortController();
			args.upstreamSession.then(() => {
				if (!this.#abortController.signal.aborted) this.#server.send(JSON.stringify(this.#message));
			});
			this.#server.addEventListener("message", (event) => {
				const message = parseGraphQLWebSocketMessage(event.data);
				if (!message) return;
				switch (message.type) {
					case "connection_ack":
						event.preventDefault();
						this.#emitter.emit(new TypedEvent("connection_ack"));
						break;
					case "next": {
						if (message.id !== this.#message.id) break;
						const nextEvent = new TypedEvent("next", { data: message });
						this.#emitter.emit(nextEvent);
						if (nextEvent.defaultPrevented) event.preventDefault();
						break;
					}
					case "error": {
						if (message.id !== this.#message.id) break;
						const errorEvent = new TypedEvent("error", { data: message });
						this.#emitter.emit(errorEvent);
						if (errorEvent.defaultPrevented) {
							event.preventDefault();
							break;
						}
						this.#onTerminate();
						break;
					}
					case "complete": {
						if (message.id !== this.#message.id) break;
						const completeEvent = new TypedEvent("complete", { data: message });
						this.#emitter.emit(completeEvent);
						if (completeEvent.defaultPrevented) {
							event.preventDefault();
							break;
						}
						this.#onTerminate();
						break;
					}
				}
			}, { signal: this.#abortController.signal });
		}
		/**
		* Add an event listener to the given GraphQL subscription event.
		*
		* @example
		* const onPostAddedSubscription = subscription.passthrough()
		* onPostAddedSubscription.addEventListener('next', (event) => {
		*   console.log(event.data)
		*   // { id, payload, ... }
		* })
		*/
		addEventListener(event, listener) {
			this.#emitter.on(event, listener, { signal: this.#abortController.signal });
		}
		/**
		* Unsubscribe from this passthrough GraphQL subscription.
		* This stops this subscription on the original server.
		*
		* @note Unsubscribing from the original subscription has no
		* effect on the intercepted `subscription` object.
		*
		* @example
		* const onPostAddedSubscription = subscription.passthrough()
		* onPostAddedSubscription.unsubscribe()
		*/
		unsubscribe() {
			this.#abortController.abort();
			this.#emitter.removeAllListeners();
			/**
			* @note Complete this subscription instead of closing the server
			* connection. That connection is shared by every subscription of
			* this client, and closing it would terminate the unrelated ones.
			*/
			this.#server.send(createCompleteMessage({ id: this.#message.id }));
		}
	};
	function logGraphQLFrame(args) {
		const timestamp = getTimestamp({ milliseconds: true });
		if (typeof args.payload === "undefined") {
			console.log(devUtils.formatMessage(`${timestamp} %c${args.label}%c`), `color:${args.color}`, "color:inherit");
			return;
		}
		console.groupCollapsed(devUtils.formatMessage(`${timestamp} %c${args.label}%c`), `color:${args.color}`, "color:inherit");
		console.log(args.payload);
		console.groupEnd();
	}
	/**
	* Attach a GraphQL-aware logger to the intercepted WebSocket connection.
	* Unlike the raw WebSocket logger, this logger prints parsed
	* `graphql-transport-ws` frames relevant to the subscription.
	*/
	function attachGraphQLSubscriptionLogger(connection) {
		const { client } = connection;
		const abortController = new AbortController();
		logGraphQLFrame({
			color: colors.system,
			label: `GraphQL subscription connection ${toPublicUrl(client.url)}`
		});
		client.addEventListener("message", (event) => {
			const message = parseGraphQLWebSocketMessage(event.data);
			if (!message) return;
			switch (message.type) {
				case "subscribe":
					logGraphQLFrame({
						color: colors.outgoing,
						label: `subscribe (id: ${message.id})`,
						payload: message.payload
					});
					break;
				case "complete": logGraphQLFrame({
					color: colors.outgoing,
					label: `complete (id: ${message.id})`
				});
			}
		}, { signal: abortController.signal });
		const originalClientSend = client.send;
		client.send = new Proxy(client.send, { apply: (target, thisArg, args) => {
			const [data] = args;
			const message = parseGraphQLWebSocketMessage(data);
			if (message) switch (message.type) {
				case "next":
					logGraphQLFrame({
						color: colors.mocked,
						label: `next (id: ${message.id})`,
						payload: message.payload
					});
					break;
				case "error":
					logGraphQLFrame({
						color: colors.mocked,
						label: `error (id: ${message.id})`,
						payload: message.payload
					});
					break;
				case "complete": logGraphQLFrame({
					color: colors.mocked,
					label: `complete (id: ${message.id})`
				});
			}
			return Reflect.apply(target, thisArg, args);
		} });
		return function detachLogger() {
			abortController.abort();
			client.send = originalClientSend;
		};
	}
	/**
	* Create a `subscription()` handler factory bound to the given GraphQL
	* endpoint. All subscription handlers created by the factory share a single
	* subscription transport and a single WebSocket upgrade handler, both
	* attached to each handler as siblings.
	*
	* @example
	* const subscription = createGraphQLSubscriptionHandler('https://api.example.com/graphql')
	* subscription('OnPostAdded', ({ subscription }) => {
	*   subscription.publish({ data: { postAdded: { id: 'abc-123' } } })
	* })
	*/
	function createGraphQLSubscriptionHandler(url) {
		const webSocketUrl = typeof url === "string" ? url.replace(/^http/, "ws") : url;
		const transport = new GraphQLSubscriptionTransportHandler(webSocketUrl);
		const upgradeHandler = http.get(({ request }) => {
			return request.headers.get("upgrade")?.toLowerCase() === "websocket" && includesGraphQLProtocol(request.headers.get("sec-websocket-protocol")) && matchRequestUrl(new URL(resolveWebSocketUrl(request.url)), webSocketUrl).matches;
		}, webSocketUpgrade);
		return (operationName, resolver, options) => {
			return attachSiblingHandlers(new GraphQLSubscriptionHandler({
				url: webSocketUrl,
				operationName,
				transport,
				resolver,
				options
			}), [transport, upgradeHandler]);
		};
	}
	//#endregion
	//#region src/graphql/graphql.ts
	function createScopedGraphQLHandler(operationType, url) {
		return (predicate, resolver, options = {}) => {
			return new GraphQLHandler(operationType, predicate, url, resolver, options);
		};
	}
	function createGraphQLOperationHandler(url, subscriptionFactory) {
		/**
		* @note An explicitly generic function so the subscription sibling
		* can be created with the same `Query`/`Variables` types as the
		* operation resolver, without casting its resolver info.
		*/
		return (resolver, options) => {
			const handler = new GraphQLHandler("all", /* @__PURE__ */ new RegExp(".*"), url, resolver, options);
			if (!subscriptionFactory) return handler;
			return attachSiblingHandlers(handler, [subscriptionFactory(/* @__PURE__ */ new RegExp(".*"), ({ operationName, subscription, request, finalize }) => {
				/**
				* @note Subscriptions are resolved imperatively, so the return
				* value of the resolver is ignored. The request describes the
				* WebSocket connection this subscription is multiplexed over.
				*/
				resolver({
					operationName,
					query: subscription.query,
					variables: subscription.variables,
					cookies: getAllRequestCookies(request),
					request,
					requestId: createRequestId(),
					finalize
				});
			}, options)]);
		};
	}
	/**
	* A namespace to intercept and mock GraphQL operations
	*
	* @example
	* const api = graphql.link('https://api.example.com/graphql')
	* api.query('GetUser', resolver)
	* api.mutation('DeletePost', resolver)
	*
	* @see {@link https://mswjs.io/docs/api/graphql `graphql` API reference}
	*/
	const graphql = { 
	/**
	* Intercepts GraphQL operations scoped by the given URL.
	*
	* @example
	* const github = graphql.link('https://api.github.com/graphql')
	* github.query('GetRepo', resolver)
	*
	* @see {@link https://mswjs.io/docs/api/graphql#graphqllinkurl `graphql.link()` API reference}
	*/
link(url) {
		/**
		* @note Create the subscription handler factory once per link so
		* the `subscription()` and `operation()` handlers share the same
		* underlying subscription transport (deduped by reference).
		*/
		const subscription = createGraphQLSubscriptionHandler(url);
		return {
			operation: createGraphQLOperationHandler(url, subscription),
			query: createScopedGraphQLHandler("query", url),
			mutation: createScopedGraphQLHandler("mutation", url),
			subscription
		};
	} };
	//#endregion
	exports.GraphQLHandler = GraphQLHandler;
	exports.GraphQLPassthroughSubscription = GraphQLPassthroughSubscription;
	exports.GraphQLSubscription = GraphQLSubscription;
	exports.GraphQLSubscriptionHandler = GraphQLSubscriptionHandler;
	exports.HttpHandler = HttpHandler;
	exports.HttpMethods = HttpMethods;
	exports.HttpResponse = HttpResponse;
	exports.RequestHandler = RequestHandler;
	exports.WebSocketConnectionEvent = WebSocketConnectionEvent;
	exports.WebSocketExtension = WebSocketExtension;
	exports.WebSocketHandler = WebSocketHandler;
	exports.bypass = bypass;
	exports.createDefaultNetworkOptions = createDefaultNetworkOptions;
	exports.createGraphQLSubscriptionHandler = createGraphQLSubscriptionHandler;
	exports.defaultNetworkOptions = defaultNetworkOptions;
	exports.delay = delay;
	exports.getCleanUrlString = getCleanUrlString;
	exports.getResponse = getResponse;
	exports.graphql = graphql;
	exports.http = http;
	exports.isCommonAssetRequest = isCommonAssetRequest;
	exports.isPassthroughResponse = isPassthroughResponse;
	exports.matchRequestUrl = matchRequestUrl;
	exports.passthrough = passthrough;
	exports.setupWorker = setupWorker;
	exports.sse = sse;
	exports.ws = ws;
	return exports;
})({});

//# sourceMappingURL=index.js.map