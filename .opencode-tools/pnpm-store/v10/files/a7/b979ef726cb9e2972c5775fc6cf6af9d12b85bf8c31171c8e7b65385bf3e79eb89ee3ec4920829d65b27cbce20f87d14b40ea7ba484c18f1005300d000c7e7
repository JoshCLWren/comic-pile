import { a as matchRequestUrl } from "./cookie-store.js";
import { t as http } from "./http.js";
import { FetchResponse, resolveWebSocketUrl } from "@mswjs/interceptors";
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
export { webSocketUpgrade as n, createWebSocketUpgradeHandler as t };

//# sourceMappingURL=websocket-upgrade.js.map