import { a as matchRequestUrl, c as isStringEqual, h as devUtils, p as httpStatusMessages, r as toPublicUrl, s as getTimestamp, t as cookieStore } from "./cookie-store.js";
import { t as RequestHandler } from "./request-handler.js";
import { getCleanUrlString } from "../utils/get-clean-url-string.js";
import { parseCookie } from "cookie";
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
export { serializeRequest as a, serializeResponse as i, HttpMethods as n, getStatusCodeColor as o, getAllRequestCookies as r, HttpHandler as t };

//# sourceMappingURL=http-handler.js.map