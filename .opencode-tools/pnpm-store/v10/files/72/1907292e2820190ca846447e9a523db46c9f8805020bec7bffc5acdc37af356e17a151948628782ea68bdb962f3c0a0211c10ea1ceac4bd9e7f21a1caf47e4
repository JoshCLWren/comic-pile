import { invariant } from "outvariant";
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
	invariant(!request.bodyUsed, "Failed to create a bypassed request to \"%s %s\": given request instance already has its body read. Make sure to clone the intercepted request if you wish to read its body before bypassing it.", request.method, request.url);
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
export { bypass };

//# sourceMappingURL=bypass.js.map