//#region src/utils/is-common-asset-request.d.ts
/**
 * Determines if the given request is a static asset request.
 * Useful when deciding which unhandled requests to ignore.
 * @note Despite being ignored, you can still intercept and mock
 * static assets by creating request handlers for them.
 *
 * @example
 * import { isCommonAssetRequest } from 'msw'
 * import { HttpNetworkFrame } from 'msw/experimental'
 *
 * await worker.start({
 *   onUnhandledFrame({ frame, defaults }) {
 *     if (frame instanceof HttpNetworkFrame && !isCommonAssetRequest(frame.data.request)) {
 *       defaults.warn()
 *     }
 *   }
 * })
 */
export declare function isCommonAssetRequest(request: Request): boolean;
//#endregion
//# sourceMappingURL=is-common-asset-request.d.ts.map