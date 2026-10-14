import { t as executeHandlers } from "../_chunks/execute-handlers.js";
import { createRequestId } from "@mswjs/interceptors";
//#region src/utils/get-response.ts
/**
* Finds a response for the given request instance
* in the array of request handlers.
* @param handlers The array of request handlers.
* @param request The `Request` instance.
* @param resolutionContext Request resolution options.
* @returns {Response} A mocked response, if any.
*/
const getResponse = async (handlers, request, resolutionContext) => {
	return (await executeHandlers({
		request,
		requestId: createRequestId(),
		handlers,
		resolutionContext
	}))?.response;
};
//#endregion
export { getResponse };

//# sourceMappingURL=get-response.js.map