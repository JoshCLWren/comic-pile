//#region src/utils/get-clean-url-string.ts
const REDUNDANT_CHARACTERS_EXP = /[?|#].*$/g;
/**
* Removes search parameters and the fragment from a given URL string.
* Unlike `getCleanUrl()` from Interceptors, accepts relative URLs and
* path patterns (e.g. "/user/:id?") since it never parses the input as a URL.
*/
function getCleanUrlString(url) {
	if (url.endsWith("?")) return url;
	return url.replace(REDUNDANT_CHARACTERS_EXP, "");
}
//#endregion
export { getCleanUrlString };

//# sourceMappingURL=get-clean-url-string.js.map