import { NetworkReadyState, defineNetwork } from "msw/experimental";
//#region src/vite/runtime.ts
const hot = import.meta.hot;
const hotData = hot?.data;
async function createNetwork(options) {
	while (hotData?.disposeNetwork) {
		const disposePrevious = hotData.disposeNetwork;
		await disposePrevious();
		if (hotData.disposeNetwork === disposePrevious) break;
	}
	const network = defineNetwork(options);
	if (hot && hotData) {
		let resumeAfterUpdate = false;
		let retired = false;
		let pendingOperation;
		const configure = network.configure;
		const enable = network.enable;
		const disable = network.disable;
		const runOperation = (action) => {
			const result = pendingOperation ? pendingOperation.then(action) : action();
			if (result instanceof Promise) {
				const operation = result.finally(() => {
					if (pendingOperation === operation) pendingOperation = void 0;
				});
				pendingOperation = operation;
				return operation;
			}
		};
		const stop = () => {
			if (network.readyState === NetworkReadyState.ENABLED) return disable();
		};
		network.configure = (options) => {
			runOperation(() => {
				if (retired) return;
				const stopped = stop();
				if (stopped instanceof Promise) return stopped.then(() => configure(options));
				configure(options);
			});
		};
		network.enable = async () => {
			await runOperation(() => {
				if (!retired && network.readyState === NetworkReadyState.DISABLED) return enable();
			});
		};
		network.disable = async () => {
			await runOperation(stop);
		};
		const disableNetwork = async () => {
			await network.disable();
		};
		const beforeUpdate = async () => {
			resumeAfterUpdate = network.readyState === NetworkReadyState.ENABLED;
			await disableNetwork();
		};
		const afterUpdate = async () => {
			const shouldResume = resumeAfterUpdate;
			resumeAfterUpdate = false;
			if (shouldResume && network.readyState === NetworkReadyState.DISABLED) await network.enable();
		};
		hot.on("vite:beforeUpdate", beforeUpdate);
		hot.on("vite:afterUpdate", afterUpdate);
		hot.on("vite:beforeFullReload", disableNetwork);
		const disposeNetwork = async () => {
			retired = true;
			resumeAfterUpdate = false;
			hot.off("vite:beforeUpdate", beforeUpdate);
			hot.off("vite:afterUpdate", afterUpdate);
			hot.off("vite:beforeFullReload", disableNetwork);
			await disableNetwork();
		};
		hotData.disposeNetwork = disposeNetwork;
		hot.dispose(disposeNetwork);
	}
	return network;
}
//#endregion
export { createNetwork };

//# sourceMappingURL=runtime.js.map