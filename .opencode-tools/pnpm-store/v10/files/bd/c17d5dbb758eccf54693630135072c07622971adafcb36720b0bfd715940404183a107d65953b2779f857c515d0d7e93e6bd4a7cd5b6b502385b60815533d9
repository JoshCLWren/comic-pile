import { t as isObject } from "./is-object.js";
//#region src/core/utils/internal/has-ref-counted.ts
function hasRefCounted(value) {
	return isObject(value) && typeof Reflect.get(value, "ref") === "function" && typeof Reflect.get(value, "unref") === "function";
}
//#endregion
export { hasRefCounted as t };

//# sourceMappingURL=has-ref-counted.js.map