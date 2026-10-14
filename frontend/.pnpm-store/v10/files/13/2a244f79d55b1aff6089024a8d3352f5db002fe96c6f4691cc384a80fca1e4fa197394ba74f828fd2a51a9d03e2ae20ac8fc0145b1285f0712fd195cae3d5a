import { a as matchRequestUrl, h as devUtils, n as jsonParse, r as toPublicUrl, s as getTimestamp } from "../_chunks/cookie-store.js";
import { t as RequestHandler } from "../_chunks/request-handler.js";
import { a as serializeRequest, i as serializeResponse, o as getStatusCodeColor, r as getAllRequestCookies } from "../_chunks/http-handler.js";
import { t as http } from "../_chunks/http.js";
import { a as WebSocketHandler, s as kConnect, t as attachSiblingHandlers } from "../_chunks/attach-sibling-handlers.js";
import { t as colors } from "../_chunks/colors.js";
import { n as webSocketUpgrade } from "../_chunks/websocket-upgrade.js";
import { n as kDefaultContentType } from "../_chunks/symbols.js";
import { invariant } from "outvariant";
import { createRequestId, resolveWebSocketUrl } from "@mswjs/interceptors";
import { Emitter, TypedEvent } from "rettime";
import { OperationTypeNode, parse } from "graphql";
import { stringToHeaders } from "headers-polyfill";
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
			const query = url.searchParams.get("query");
			const variables = url.searchParams.get("variables") || "";
			return {
				query,
				variables: jsonParse(variables),
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
			invariant(node.operationType === operationType, "Failed to create a GraphQL handler: provided a DocumentNode with a mismatched operation type (expected \"%s\" but got \"%s\").", operationType, node.operationType);
			invariant(node.operationName, "Failed to create a GraphQL handler: provided a DocumentNode without operation name");
			return node.operationName;
		};
		if (isDocumentNode(predicate)) return getOperationName(parseDocumentNode(predicate));
		if (isDocumentTypeDecoration(predicate)) {
			const documentNode = parse(predicate.toString());
			invariant(isDocumentNode(documentNode), "Failed to create a GraphQL handler: given TypedDocumentString (%s) does not produce a valid DocumentNode", predicate);
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
		invariant(typeof operationName !== "function" && !isDocumentNode(operationName), "Failed to create a GraphQL subscription handler: custom predicates are not supported for subscriptions");
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
		invariant(connection, "Failed to passthrough the GraphQL subscription (\"%s\"): the underlying WebSocket connection is closed", this.query);
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
		const handler = new GraphQLSubscriptionHandler({
			url: webSocketUrl,
			operationName,
			transport,
			resolver,
			options
		});
		return attachSiblingHandlers(handler, [transport, upgradeHandler]);
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
		const subscriptionCatchAllHandler = subscriptionFactory(/* @__PURE__ */ new RegExp(".*"), ({ operationName, subscription, request, finalize }) => {
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
		}, options);
		return attachSiblingHandlers(handler, [subscriptionCatchAllHandler]);
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
export { GraphQLHandler, GraphQLPassthroughSubscription, GraphQLSubscription, GraphQLSubscriptionHandler, createGraphQLSubscriptionHandler, graphql };

//# sourceMappingURL=index.js.map