//#region src/utils/is-common-asset-request.ts
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
function isCommonAssetRequest(request) {
	const url = new URL(request.url);
	if (url.protocol === "file:") return true;
	if (/(fonts\.googleapis\.com)/.test(url.hostname)) return true;
	if (/node_modules/.test(url.pathname)) return true;
	if (url.pathname.includes("@vite")) return true;
	return /\.(s?css|less|m?jsx?|m?tsx?|html|ttf|otf|woff|woff2|eot|gif|jpe?g|png|avif|webp|svg|mp4|webm|ogg|mov|mp3|wav|ogg|flac|aac|pdf|txt|csv|json|xml|md|zip|tar|gz|rar|7z)$/i.test(url.pathname);
}
//#endregion
export { isCommonAssetRequest };

//# sourceMappingURL=is-common-asset-request.js.map