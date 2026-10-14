import { p as HttpResponse } from "../_chunks/request-handler.js";
//#region src/utils/passthrough.d.ts
export declare const REQUEST_INTENTION_HEADER_NAME = "x-msw-intention";
export declare enum RequestIntention {
  passthrough = "passthrough"
}
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
export declare function passthrough(): HttpResponse<any>;
/**
 * Returns `true` if the given response was created by `passthrough()`.
 *
 * @example
 * const response = passthrough()
 * isPassthroughResponse(response) // true
 */
export declare function isPassthroughResponse(response: Response): boolean;
//#endregion
//# sourceMappingURL=passthrough.d.ts.map