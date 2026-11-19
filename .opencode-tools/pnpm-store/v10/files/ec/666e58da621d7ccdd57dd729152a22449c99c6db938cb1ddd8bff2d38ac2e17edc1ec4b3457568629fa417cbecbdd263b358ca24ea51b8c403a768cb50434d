import { t as HttpHandler } from "./http-handler.js";
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
export { http as t };

//# sourceMappingURL=http.js.map