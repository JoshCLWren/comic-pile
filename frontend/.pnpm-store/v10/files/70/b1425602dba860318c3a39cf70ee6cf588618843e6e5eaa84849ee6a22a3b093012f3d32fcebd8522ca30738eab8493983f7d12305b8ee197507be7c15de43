import { getCleanUrlString } from "../utils/get-clean-url-string.js";
import { isNodeProcess } from "is-node-process";
import { format, invariant } from "outvariant";
import { getCleanUrl } from "@mswjs/interceptors";
import { matchPattern } from "@msw/url";
import { Cookie, CookieJar, MemoryCookieStore } from "tough-cookie";
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
//#region src/core/utils/internal/is-string-equal.ts
/**
* Performs a case-insensitive comparison of two given strings.
*/
function isStringEqual(actual, expected) {
	return actual.toLowerCase() === expected.toLowerCase();
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
	const maybeAbsoluteUrl = getAbsoluteUrl(path, baseUrl);
	return getCleanUrlString(maybeAbsoluteUrl);
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
	const normalizedPath = normalizePath(pattern, baseUrl);
	return matchPattern(normalizedPath, cleanUrl);
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
		invariant(typeof localStorage !== "undefined", "Failed to create a CookieStore: `localStorage` is not available in this environment. This is likely an issue with your environment, which has been detected as browser (or browser-like) environment and must implement global browser APIs correctly.");
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
export { Handler as _, matchRequestUrl as a, isStringEqual as c, getRawSetCookie as d, normalizeResponseInit as f, getCallFrame as g, devUtils as h, isPath as i, copyResponseOwnProperties as l, InternalError as m, jsonParse as n, isAbsoluteUrl as o, httpStatusMessages as p, toPublicUrl as r, getTimestamp as s, cookieStore as t, decorateResponse as u };

//# sourceMappingURL=cookie-store.js.map