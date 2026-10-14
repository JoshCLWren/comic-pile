//#region src/utils/passthrough.ts
const REQUEST_INTENTION_HEADER_NAME = "x-msw-intention";
let RequestIntention = /* @__PURE__ */ function(RequestIntention) {
	RequestIntention["passthrough"] = "passthrough";
	return RequestIntention;
}({});
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
export { REQUEST_INTENTION_HEADER_NAME, RequestIntention, isPassthroughResponse, passthrough };

//# sourceMappingURL=passthrough.js.map