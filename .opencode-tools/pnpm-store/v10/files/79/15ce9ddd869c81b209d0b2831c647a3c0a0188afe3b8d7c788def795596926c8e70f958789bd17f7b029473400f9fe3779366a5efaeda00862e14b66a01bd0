import { i as isPath } from "./cookie-store.js";
import { a as WebSocketHandler, c as kEmitter, t as attachSiblingHandlers } from "./attach-sibling-handlers.js";
import { t as hasRefCounted } from "./has-ref-counted.js";
import { n as webSocketUpgrade, t as createWebSocketUpgradeHandler } from "./websocket-upgrade.js";
import { invariant } from "outvariant";
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
	invariant(url, "Expected a WebSocket server URL but got undefined");
	invariant(isPath(url), "Expected a WebSocket server URL to be a valid path but got %s", typeof url);
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
export { ws as t };

//# sourceMappingURL=ws.js.map