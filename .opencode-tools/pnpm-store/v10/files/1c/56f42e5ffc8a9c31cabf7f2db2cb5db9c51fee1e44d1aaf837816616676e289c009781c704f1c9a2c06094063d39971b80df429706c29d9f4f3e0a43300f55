//#region src/core/utils/execute-handlers.ts
/**
* Executes the list of request handlers against the given request.
* Returns the execution result object containing any matching request
* handler and any mocked response it returned.
*/
const executeHandlers = async ({ request, requestId, handlers, resolutionContext }) => {
	let matchingHandler = null;
	let result = null;
	for (const handler of handlers) {
		result = await handler.run({
			request,
			requestId,
			resolutionContext
		});
		if (result !== null) matchingHandler = handler;
		if (result?.response) break;
	}
	if (matchingHandler) return {
		handler: matchingHandler,
		parsedResult: result?.parsedResult,
		response: result?.response
	};
	return null;
};
//#endregion
export { executeHandlers as t };

//# sourceMappingURL=execute-handlers.js.map