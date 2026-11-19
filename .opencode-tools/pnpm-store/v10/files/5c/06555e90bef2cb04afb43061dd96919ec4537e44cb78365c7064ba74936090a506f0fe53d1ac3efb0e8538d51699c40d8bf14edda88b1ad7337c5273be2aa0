import * as fs from "node:fs";
import { fileURLToPath } from "node:url";
//#region src/vite/plugin.ts
const WORKER_FILENAME = "mockServiceWorker.js";
const WORKER_SCRIPT_PATH = new URL("../mockServiceWorker.js", import.meta.url);
const VIRTUAL_MODULE_ID = "virtual:msw";
const RUNTIME_PATH = fileURLToPath(new URL("./runtime.js", import.meta.url));
/**
* A Vite plugin for Mock Service Worker.
*
* @example
* // vite.config.ts
* import { msw } from 'msw/vite'
*
* export default defineConfig({
*   plugins: [msw()]
* })
*
* @example
* // src/{client,server}.ts
* if (import.meta.env.DEV) {
*   const { network } = await import('virtual:msw')
*   const { handlers } = await import('./mocks/handlers')
*
*   network.configure({ handlers })
*   await network.enable()
* }
*
* @remarks
* The worker script is served during development and emitted next to any
* client bundle that imports `virtual:msw`. Guard mocking setup with
* `import.meta.env.DEV` to exclude both from production builds.
*
* For application TypeScript projects that do not include the Vite config,
* add `/// <reference types="msw/vite/client" />` to an included declaration file.
*/
function msw(options = {}) {
	const mode = options.mode ?? "auto";
	let workerUrl = `/${WORKER_FILENAME}`;
	const environmentsUsingNetwork = /* @__PURE__ */ new Set();
	return {
		name: "msw",
		resolveId(id) {
			if (mode === "worker-only") return;
			if (id === VIRTUAL_MODULE_ID) return `\0${VIRTUAL_MODULE_ID}`;
		},
		load(id) {
			if (mode === "worker-only" || id !== `\0${VIRTUAL_MODULE_ID}`) return;
			if (this.environment.config.consumer === "server") return `
import { defaultNetworkOptions } from 'msw/node'
import { createNetwork } from ${JSON.stringify(RUNTIME_PATH)}
export const network = await createNetwork(defaultNetworkOptions)
`;
			environmentsUsingNetwork.add(this.environment.name);
			return `
import { createDefaultNetworkOptions } from 'msw/browser'
import { createNetwork } from ${JSON.stringify(RUNTIME_PATH)}
export const network = await createNetwork(createDefaultNetworkOptions(${JSON.stringify(workerUrl)}))
`;
		},
		configResolved(config) {
			workerUrl = `${config.base === "./" ? config.base : new URL(config.base, "http://localhost").pathname}${WORKER_FILENAME}`;
		},
		generateBundle() {
			if (this.environment.config.consumer !== "client") return;
			if (mode === "auto" && !environmentsUsingNetwork.has(this.environment.name)) return;
			this.emitFile({
				type: "asset",
				fileName: WORKER_FILENAME,
				source: fs.readFileSync(WORKER_SCRIPT_PATH, "utf8")
			});
		},
		configureServer(server) {
			const workerScript = fs.readFileSync(WORKER_SCRIPT_PATH, "utf8");
			server.middlewares.use((request, response, next) => {
				if (new URL(request.url ?? "/", "http://localhost").pathname !== workerUrl) {
					next();
					return;
				}
				response.writeHead(200, {
					"cache-control": "no-cache",
					"content-type": "application/javascript; charset=utf-8",
					"service-worker-allowed": "/"
				});
				response.end(workerScript);
			});
		}
	};
}
//#endregion
export { msw };

//# sourceMappingURL=index.js.map